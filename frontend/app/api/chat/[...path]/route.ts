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
  const body = request.method === "GET" ? undefined : await request.text();

  const response = await fetch(targetUrl, {
    method: request.method,
    headers: {
      "Content-Type": request.headers.get("content-type") ?? "application/json",
    },
    body,
  });

  const headers = new Headers();
  const contentType = response.headers.get("content-type");
  if (contentType) {
    headers.set("content-type", contentType);
  }

  return new Response(response.body, {
    status: response.status,
    headers,
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
