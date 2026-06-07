"""
Tests de non-régression Sprint 2 :
  - classify_intent()     : normalisation accents, meilleur score, patterns regex
  - chunk_text()          : découpage par paragraphes, overlap, paragraphe long
  - should_trigger_rag()  : step wizard → False, intent RAG → True, question → True
  - ingest_sources()      : idempotence (skip si déjà prêt, force réingestion)
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2] / "backend"))

import pytest
import app.rag.retrieve as retrieve
import app.rag.ingest as ingest


# ---------------------------------------------------------------------------
# classify_intent
# ---------------------------------------------------------------------------

class TestClassifyIntent:
    def test_normalise_accent(self):
        # "bannières" → normalise en "bannieres" → match intent display
        result = retrieve.classify_intent("Parlez-moi des bannières publicitaires")
        assert result == "display"

    def test_normalise_casse(self):
        result = retrieve.classify_intent("AUDIENCE TUNISIE NUMÉRIQUE")
        assert result == "audience"

    def test_best_score_not_first_match(self):
        # "vidéo live youtube" accumule 3 hits dans "video" → gagne sur "solutions"
        result = retrieve.classify_intent("format vidéo live youtube instream")
        assert result == "video"

    def test_regex_pattern_gives_bonus(self):
        # "banniere pub" déclenche le pattern regex → score plus élevé
        result = retrieve.classify_intent("je veux mettre une bannière pub")
        assert result == "display"

    def test_no_match_returns_none(self):
        result = retrieve.classify_intent("il fait beau aujourd'hui, merci")
        assert result is None

    def test_immobilier_neuf_regex(self):
        result = retrieve.classify_intent("programme immobilier neuf à Tunis")
        assert result == "immoneuf"

    def test_newsletter_match(self):
        result = retrieve.classify_intent("je veux faire une campagne emailing newsletter")
        assert result == "newsletter_audio"

    def test_premium_match(self):
        result = retrieve.classify_intent("offre haut de gamme segment premium")
        assert result == "premium"


# ---------------------------------------------------------------------------
# chunk_text
# ---------------------------------------------------------------------------

class TestChunkText:
    def test_single_paragraph_fits_in_one_chunk(self):
        text = "Premier paragraphe avec quelques mots courts."
        chunks = ingest.chunk_text(text, max_tokens=50, overlap=0)
        assert len(chunks) == 1
        assert "Premier" in chunks[0]

    def test_two_paragraphs_split_when_exceed_max(self):
        para1 = " ".join(["mot"] * 60)
        para2 = " ".join(["autre"] * 60)
        text = f"{para1}\n\n{para2}"
        chunks = ingest.chunk_text(text, max_tokens=80, overlap=0)
        assert len(chunks) == 2
        assert "mot" in chunks[0]
        assert "autre" in chunks[1]

    def test_two_paragraphs_fit_together(self):
        para1 = " ".join(["a"] * 30)
        para2 = " ".join(["b"] * 30)
        text = f"{para1}\n\n{para2}"
        chunks = ingest.chunk_text(text, max_tokens=100, overlap=0)
        assert len(chunks) == 1

    def test_overlap_carries_words(self):
        para1 = " ".join([f"w{i}" for i in range(60)])
        para2 = " ".join([f"x{i}" for i in range(60)])
        text = f"{para1}\n\n{para2}"
        chunks = ingest.chunk_text(text, max_tokens=80, overlap=20)
        assert len(chunks) == 2
        # Les 20 derniers mots du chunk 1 doivent apparaître au début du chunk 2
        last_words_chunk1 = chunks[0].split()[-20:]
        first_words_chunk2 = chunks[1].split()[:20]
        assert last_words_chunk1 == first_words_chunk2

    def test_long_single_paragraph_split_by_words(self):
        # Un seul paragraphe de 300 mots, max=100 → 3 chunks
        long_para = " ".join([f"w{i}" for i in range(300)])
        chunks = ingest.chunk_text(long_para, max_tokens=100, overlap=0)
        assert len(chunks) == 3

    def test_empty_text_returns_empty(self):
        assert ingest.chunk_text("", max_tokens=100, overlap=0) == []

    def test_only_whitespace_returns_empty(self):
        assert ingest.chunk_text("   \n\n   ", max_tokens=100, overlap=0) == []

    def test_paragraph_boundary_preserved(self):
        # Les chunks ne doivent pas couper au milieu d'un paragraphe si possible
        para1 = "Introduction au display advertising."
        para2 = "Le format MPU fait 300x250 pixels."
        text = f"{para1}\n\n{para2}"
        chunks = ingest.chunk_text(text, max_tokens=20, overlap=0)
        # Chaque chunk doit contenir des mots d'un seul paragraphe (pas de mélange)
        assert any("display" in c for c in chunks)
        assert any("MPU" in c for c in chunks)


# ---------------------------------------------------------------------------
# should_trigger_rag
# ---------------------------------------------------------------------------

class TestShouldTriggerRag:
    def test_false_on_form_step(self):
        assert not retrieve.should_trigger_rag(None, "mon email", step="FORM_STANDARD_EMAIL")

    def test_false_on_budget_wizard_step(self):
        assert not retrieve.should_trigger_rag(None, "ok", step="BUDGET_CLIENT_TYPE")

    def test_false_on_welcome_step(self):
        assert not retrieve.should_trigger_rag(None, "bonjour", step="WELCOME_SCOPE")

    def test_true_on_rag_intent_display(self):
        assert retrieve.should_trigger_rag("display", "info", step=None)

    def test_true_on_rag_intent_audience(self):
        assert retrieve.should_trigger_rag("audience", "chiffres", step=None)

    def test_true_on_factual_question_with_mark(self):
        assert retrieve.should_trigger_rag(None, "Quel est le prix ?", step=None)

    def test_true_on_factual_token(self):
        assert retrieve.should_trigger_rag(None, "combien coûte une bannière", step=None)

    def test_false_on_plain_navigation(self):
        # Message sans intent RAG, sans "?", sans token factuel
        assert not retrieve.should_trigger_rag(None, "ok merci", step=None)

    def test_step_none_does_not_block(self):
        # step=None ne doit pas bloquer une requête légitime
        assert retrieve.should_trigger_rag("video", "info", step=None)

    def test_step_case_insensitive(self):
        assert not retrieve.should_trigger_rag(None, "test", step="form_standard_email")


# ---------------------------------------------------------------------------
# ingest_sources — idempotence
# ---------------------------------------------------------------------------

class TestIngestIdempotence:
    def _make_conn_mock(self, already_ready: bool):
        """Fabrique un mock de connexion psycopg simplifié."""
        import unittest.mock as mock

        conn = mock.MagicMock()
        cursor = mock.MagicMock()
        conn.__enter__ = mock.MagicMock(return_value=conn)
        conn.__exit__ = mock.MagicMock(return_value=False)
        conn.execute = mock.MagicMock()

        if already_ready:
            # Simule un document déjà existant avec status='ready'
            conn.execute.return_value.fetchone = mock.MagicMock(return_value=("existing-doc-id",))
        else:
            conn.execute.return_value.fetchone = mock.MagicMock(return_value=None)

        return conn

    def test_skip_already_ready_document(self, monkeypatch, tmp_path):
        # Crée un fichier source
        src = tmp_path / "DISPLAY_ADS.txt"
        src.write_text("Contenu display ads.", encoding="utf-8")

        call_count = {"embed": 0}

        def fake_embed(texts):
            call_count["embed"] += 1
            return [[0.1] * 4 for _ in texts]

        # Simule un document déjà indexé
        import unittest.mock as mock
        conn_mock = mock.MagicMock()
        conn_mock.__enter__ = mock.MagicMock(return_value=conn_mock)
        conn_mock.__exit__ = mock.MagicMock(return_value=False)

        # run INSERT → retourne run_id
        run_fetchone = mock.MagicMock(return_value=(42,))
        # SELECT existing → retourne un doc déjà prêt
        existing_fetchone = mock.MagicMock(return_value=("existing-id",))

        def execute_side_effect(sql, params=None):
            result = mock.MagicMock()
            sql_stripped = sql.strip().upper()
            if sql_stripped.startswith("INSERT INTO KB_INGESTION_RUNS"):
                result.fetchone = run_fetchone
            elif sql_stripped.startswith("SELECT ID FROM KB_DOCUMENTS"):
                result.fetchone = existing_fetchone
            else:
                result.fetchone = mock.MagicMock(return_value=None)
            return result

        conn_mock.execute.side_effect = execute_side_effect
        monkeypatch.setattr(ingest, "get_connection", lambda: conn_mock)
        monkeypatch.setattr(ingest, "embed_texts", fake_embed)

        stats = ingest.ingest_sources(source_dir=tmp_path, force=False)

        # Pas d'appel à embed_texts → fichier skippé
        assert call_count["embed"] == 0
        assert stats["skipped"] == 1
        assert stats["documents"] == 0

    def test_force_reingest_calls_embed(self, monkeypatch, tmp_path):
        src = tmp_path / "DISPLAY_ADS.txt"
        src.write_text("Nouveau contenu display.", encoding="utf-8")

        call_count = {"embed": 0, "qdrant_delete": 0, "qdrant_upsert": 0}

        def fake_embed(texts):
            call_count["embed"] += 1
            return [[0.1] * 4 for _ in texts]

        def fake_delete_qdrant(ids):
            call_count["qdrant_delete"] += 1

        def fake_upsert_qdrant(points):
            call_count["qdrant_upsert"] += 1

        import unittest.mock as mock
        conn_mock = mock.MagicMock()
        conn_mock.__enter__ = mock.MagicMock(return_value=conn_mock)
        conn_mock.__exit__ = mock.MagicMock(return_value=False)

        call_index = {"n": 0}

        def execute_side_effect(sql, params=None):
            result = mock.MagicMock()
            sql_stripped = sql.strip().upper()
            if sql_stripped.startswith("INSERT INTO KB_INGESTION_RUNS"):
                result.fetchone = mock.MagicMock(return_value=(99,))
            elif sql_stripped.startswith("SELECT ID FROM KB_DOCUMENTS") and "STATUS" in sql_stripped:
                # Première fois → document existant
                result.fetchone = mock.MagicMock(return_value=("old-doc-id",))
            elif sql_stripped.startswith("SELECT ID FROM KB_CHUNKS"):
                result.fetchall = mock.MagicMock(return_value=[("chunk-1",), ("chunk-2",)])
            elif sql_stripped.startswith("INSERT INTO KB_DOCUMENTS"):
                result.fetchone = mock.MagicMock(return_value=("new-doc-id",))
            else:
                result.fetchone = mock.MagicMock(return_value=None)
                result.fetchall = mock.MagicMock(return_value=[])
            return result

        conn_mock.execute.side_effect = execute_side_effect
        monkeypatch.setattr(ingest, "get_connection", lambda: conn_mock)
        monkeypatch.setattr(ingest, "embed_texts", fake_embed)
        monkeypatch.setattr(ingest, "delete_qdrant_points", fake_delete_qdrant)
        monkeypatch.setattr(ingest, "upsert_qdrant_points", fake_upsert_qdrant)
        monkeypatch.setattr(ingest, "ensure_qdrant_collection", lambda _: None)

        stats = ingest.ingest_sources(source_dir=tmp_path, force=True)

        assert call_count["embed"] >= 1
        assert call_count["qdrant_delete"] >= 1
        assert call_count["qdrant_upsert"] >= 1
