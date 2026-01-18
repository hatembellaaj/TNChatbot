const resolveBackendBase = (request: Request) => {
  const configured =
    process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL;
  if (configured) {
    return configured;
  }

  const host = request.headers.get("host");
  if (host) {
    const [hostname, port] = host.split(":");
    if (port === "19080") {
      return `http://${hostname}:19081`;
    }
    if (port === "3000") {
      return `http://${hostname}:8000`;
    }
    return `http://${host}`;
  }

  return "http://localhost:8000";
};

type RouteParams = {
  params: {
    path?: string[];
  };
};

const forwardRequest = async (request: Request, path: string) => {
  const backendBase = resolveBackendBase(request);
  const targetUrl = new URL(`/api/chat/${path}`, backendBase);
  const requestUrl = new URL(request.url);
  targetUrl.search = requestUrl.search;
  const body =
    request.method === "GET" || request.method === "HEAD"
      ? undefined
      : request.body ?? (await request.text());

  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.delete("content-length");
  headers.set(
    "x-forwarded-host",
    request.headers.get("host") ?? "unknown",
  );

  const response = await fetch(targetUrl, {
    method: request.method,
    headers,
    body,
    duplex: "half",
  });

  const responseHeaders = new Headers();
  const contentType = response.headers.get("content-type");
  if (contentType) {
    responseHeaders.set("content-type", contentType);
  }

  return new Response(response.body, {
    status: response.status,
    headers: responseHeaders,
  });
};

export async function POST(request: Request, { params }: RouteParams) {
  const path = params.path?.join("/") ?? "";
  try {
    return await forwardRequest(request, path);
  } catch (error) {
    console.error("[TNChatbot] Proxy request failed.", error);
    return new Response("Backend unavailable", { status: 502 });
  }
}

export async function GET(request: Request, { params }: RouteParams) {
  const path = params.path?.join("/") ?? "";
  try {
    return await forwardRequest(request, path);
  } catch (error) {
    console.error("[TNChatbot] Proxy request failed.", error);
    return new Response("Backend unavailable", { status: 502 });
  }
}
