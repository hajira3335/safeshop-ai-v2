export async function onRequestGet({ env }) {
  return new Response(JSON.stringify({ ok: true, ai_configured: !!env.GEMINI_API_KEY }), {
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  });
}
