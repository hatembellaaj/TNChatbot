import { NextResponse } from "next/server";

const extractImageUrl = (value: unknown): string | null => {
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (/^https?:\/\//i.test(trimmed)) {
      return trimmed;
    }
    return null;
  }

  if (Array.isArray(value)) {
    for (const item of value) {
      const nested = extractImageUrl(item);
      if (nested) {
        return nested;
      }
    }
    return null;
  }

  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    const prioritizedKeys = ["image", "image_url", "imageUrl", "url", "src"];
    for (const key of prioritizedKeys) {
      if (key in record) {
        const nested = extractImageUrl(record[key]);
        if (nested) {
          return nested;
        }
      }
    }

    for (const nestedValue of Object.values(record)) {
      const nested = extractImageUrl(nestedValue);
      if (nested) {
        return nested;
      }
    }
  }

  return null;
};

export async function GET() {
  try {
    const response = await fetch("https://jsondata.tunisienumerique.com/pub.json", {
      next: { revalidate: 60 },
    });
    if (!response.ok) {
      return NextResponse.json(
        { imageUrl: null, reason: `status_${response.status}` },
        { status: 200 },
      );
    }
    const payload = (await response.json()) as unknown;
    const imageUrl = extractImageUrl(payload);
    return NextResponse.json({ imageUrl });
  } catch (error) {
    return NextResponse.json(
      {
        imageUrl: null,
        reason: error instanceof Error ? error.message : "unknown_error",
      },
      { status: 200 },
    );
  }
}
