export default function Home() {
  return (
    <main
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "#0f172a",
        color: "#f8fafc",
        padding: "2rem",
        textAlign: "center",
      }}
    >
      <div>
        <h1 style={{ fontSize: "2.5rem", marginBottom: "1rem" }}>TNChatbot</h1>
        <p style={{ fontSize: "1.1rem", maxWidth: "40rem" }}>
          Frontend Next.js prêt. Connectez le backend FastAPI sur
          <strong> http://localhost:8000</strong> et votre LLM via la variable
          <strong> LLM_URL</strong>.
        </p>
      </div>
    </main>
  );
}
