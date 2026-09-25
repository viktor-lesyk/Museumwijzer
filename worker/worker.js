/**
 * Museumwijzer Sync API Worker
 * Provides anonymous 6-digit sync code mapping for Museumwijzer lists.
 * Backed by Cloudflare Workers KV.
 */

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // Allowed CORS headers for museumwijzer domains and local testing
    const corsHeaders = {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    };

    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: corsHeaders });
    }

    // Health check
    if (url.pathname === '/api/sync/health' || url.pathname === '/health' || url.pathname === '/') {
      return new Response(JSON.stringify({ status: 'ok', service: 'museumwijzer-sync' }), {
        headers: { ...corsHeaders, 'Content-Type': 'application/json' },
      });
    }

    // POST /api/sync or / : Save/update list under a 6-digit code
    if (request.method === 'POST' && (url.pathname === '/api/sync' || url.pathname === '/api/sync/' || url.pathname === '/' || url.pathname === '')) {
      try {
        if (!env.MUSEUM_SYNC_KV) {
          return new Response(JSON.stringify({ error: 'MUSEUM_SYNC_KV binding not configured on Worker' }), {
            status: 500,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }

        const body = await request.json();
        const items = body.items || [];
        if (!Array.isArray(items)) {
          return new Response(JSON.stringify({ error: 'Invalid items array' }), {
            status: 400,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }

        // Validate or generate 6-digit code
        let code = body.code ? String(body.code).replace(/\D/g, '') : null;
        if (!code || code.length !== 6) {
          let attempts = 0;
          while (attempts < 5) {
            const candidate = String(Math.floor(100000 + Math.random() * 900000));
            const existing = await env.MUSEUM_SYNC_KV.get(`sync:${candidate}`);
            if (!existing) {
              code = candidate;
              break;
            }
            attempts++;
          }
          if (!code) {
            code = String(Math.floor(100000 + Math.random() * 900000));
          }
        }

        const payload = {
          code,
          updated_at: new Date().toISOString(),
          items: items.slice(0, 150),
        };

        // 30 days TTL (2,592,000 seconds)
        await env.MUSEUM_SYNC_KV.put(`sync:${code}`, JSON.stringify(payload), {
          expirationTtl: 2592000,
        });

        return new Response(JSON.stringify({ success: true, code, updated_at: payload.updated_at }), {
          headers: { ...corsHeaders, 'Content-Type': 'application/json' },
        });
      } catch (err) {
        return new Response(JSON.stringify({ error: err.message }), {
          status: 500,
          headers: { ...corsHeaders, 'Content-Type': 'application/json' },
        });
      }
    }

    // GET /api/sync/:code or /:code : Fetch list by 6-digit code
    const match = url.pathname.match(/(?:\/api\/sync\/|\/)(\d{6})/);
    if (request.method === 'GET' && match) {
      if (!env.MUSEUM_SYNC_KV) {
        return new Response(JSON.stringify({ error: 'MUSEUM_SYNC_KV binding not configured on Worker' }), {
          status: 500,
          headers: { ...corsHeaders, 'Content-Type': 'application/json' },
        });
      }

      const code = match[1];
      const data = await env.MUSEUM_SYNC_KV.get(`sync:${code}`);
      if (!data) {
        return new Response(JSON.stringify({ error: 'Code niet gevonden of verlopen (30 dagen)' }), {
          status: 404,
          headers: { ...corsHeaders, 'Content-Type': 'application/json' },
        });
      }
      return new Response(data, {
        headers: { ...corsHeaders, 'Content-Type': 'application/json' },
      });
    }

    return new Response(JSON.stringify({ error: 'Route not found' }), {
      status: 404,
      headers: { ...corsHeaders, 'Content-Type': 'application/json' },
    });
  },
};
