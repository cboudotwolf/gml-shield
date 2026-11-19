function readCsrfCookie(): string {
  const csrfCookie = document.cookie
    .split("; ")
    .find((cookiePart) => cookiePart.startsWith("gml_csrf="));
  return csrfCookie ? decodeURIComponent(csrfCookie.slice("gml_csrf=".length)) : "";
}

/**
 * Centralize same-origin cookies and double-submit CSRF protection.
 * The access token stays in an HttpOnly cookie and is never exposed to client code.
 */
export async function requestApi<ResponseBody>(
  resourcePath: string,
  requestOptions: RequestInit = {},
): Promise<ResponseBody> {
  const requestHeaders = new Headers(requestOptions.headers);
  if (requestOptions.body && !(requestOptions.body instanceof FormData)) {
    requestHeaders.set("Content-Type", "application/json");
  }
  if (!['GET', 'HEAD'].includes(requestOptions.method ?? "GET")) {
    requestHeaders.set("X-CSRF-Token", readCsrfCookie());
  }

  const response = await fetch(resourcePath, {
    ...requestOptions,
    headers: requestHeaders,
    credentials: "same-origin",
  });
  if (!response.ok) {
    const errorBody: { detail?: unknown } = await response.json().catch(() => ({}));
    const message = typeof errorBody.detail === "string" ? errorBody.detail : `Erreur ${response.status}`;
    throw new Error(message);
  }
  if (response.status === 204) {
    return undefined as ResponseBody;
  }
  return response.json() as Promise<ResponseBody>;
}
