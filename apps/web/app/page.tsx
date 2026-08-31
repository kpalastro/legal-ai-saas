"use client";



/**

 * LexSim AI — v1 demo surface (intake → live SSE debate → verdict),

 * one file so the whole flow is reviewable in a single screen.

 *

 * Auth: GoTrue local (auto-signup then password grant). The JWT is verified

 * SERVER-SIDE by FastAPI (signature); the browser only transports it.

 * Browser → Ollama is forbidden (S4.3) — everything goes through the API.

 */



import { useCallback, useEffect, useRef, useState } from "react";



const API_URL = "http://localhost:8000";

const GOTRUE_URL = "http://localhost:9999";



type Turn = {

  turn: number;

  role: string;

  name: string;

  content: string;

  verdict?: { lower: number; point: number; upper: number; note: string };

};

type CaseRow = { id: string; title: string; status: string };



export default function Home() {

  // ---- auth state ----

  const [token, setTokenState] = useState<string | null>(null);

  const [authErr, setAuthErr] = useState<string | null>(null);

  const [authing, setAuthing] = useState(false);

  const [email, setEmail] = useState("");

  const [password, setPassword] = useState("");



  // ---- app state ----

  const [cases, setCases] = useState<CaseRow[]>([]);

  const [title, setTitle] = useState("");

  const [turns, setTurns] = useState<Turn[]>([]);

  const [streaming, setStreaming] = useState(false);

  const [streamErr, setStreamErr] = useState<string | null>(null);

  const esRef = useRef<EventSource | null>(null);



  const refreshCases = useCallback(async (tok: string) => {

    const res = await fetch(`${API_URL}/cases`, {

      headers: { Authorization: `Bearer ${tok}` },

    });

    if (res.ok) setCases(await res.json());

  }, []);



  useEffect(() => {

    const saved = localStorage.getItem("lexsim_token");

    if (saved) {

      setTokenState(saved);

      void refreshCases(saved);

    }

    return () => {

      if (esRef.current) esRef.current.close();

    };

    // eslint-disable-next-line react-hooks/exhaustive-deps

  }, []);



  async function auth(e: React.FormEvent) {

    e.preventDefault();

    setAuthErr(null);

    setAuthing(true);

    try {

      const common = { "Content-Type": "application/json" };

      await fetch(`${GOTRUE_URL}/signup`, {

        method: "POST",

        headers: common,

        body: JSON.stringify({ email, password }),

      }); // 200 or "already exists" — both fine

      const login = await fetch(`${GOTRUE_URL}/token?grant_type=password`, {

        method: "POST",

        headers: common,

        body: JSON.stringify({ email, password }),

      });

      if (!login.ok) {

        setAuthErr(`auth failed (${login.status})`);

        return;

      }

      const tok = await login.json();

      const t = tok.access_token as string;

      setTokenState(t);

      await refreshCases(t);

    } finally {

      setAuthing(false);

      return;

    }

  }



  async function startDebate(caseId: string) {

    setTurns([]);

    setStreamErr(null);

    setStreaming(true);

    // EventSource can't send headers, so pass the JWT as a query param —

    // the API ALSO accepts ?token= for the SSE path only (GET + EventSource).

    const es = new EventSource(`${API_URL}/cases/${caseId}/simulate?token=${token}`);

    esRef.current = es;

    es.addEventListener("turn", (e) => {

      const payload = JSON.parse((e as MessageEvent).data);

      setTurns((prev) => [...prev, payload]);

    });

    es.addEventListener("done", () => {

      setStreaming(false);

      es.close();

    });

    es.addEventListener("error", (e) => {

      setStreamErr("stream error");

      setStreaming(false);

      es.close();

    });

  }



  async function createCase() {

    if (!token || !title.trim()) return;

    const res = await fetch(`${API_URL}/cases`, {

      method: "POST",

      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },

      body: JSON.stringify({

        title,

        jurisdiction: "NSW Supreme Court",

        cause_of_action: "contract_breach",

      }),

    });

    if (res.ok) {

      setTitle("");

      await refreshCases(token);

    } else {

      setAuthErr(`create failed: ${res.status}`);

    }

  }



  // ===== render: not authed → login form =====

  return (

    <main className="min-h-screen p-8 max-w-2xl mx-auto">

      <h1 className="text-2xl font-bold mb-1">LexSim AI</h1>

      <p className="text-sm text-neutral-400 mb-6">

        Multi-agent legal debate simulation · NSW · not legal advice, simulation only.

      </p>

      {!token && (

        <section className="space-y-3">

          <h2 className="font-semibold">Sign in</h2>

          <input

            className="w-full rounded border border-neutral-700 bg-neutral-900 p-2"

            placeholder="email"

            type="email"

            value={email}

            onChange={(e) => setEmail(e.target.value)}

          />

          <input

            className="w-full rounded border border-neutral-700 bg-neutral-900 p-2"

            type="password"

            placeholder="password"

            value={password}

            onChange={(e) => setPassword(e.target.value)}

          />

          <button

            onClick={auth}

            className="w-full rounded bg-blue-600 p-2 font-medium hover:bg-blue-500"

          >

            {authing ? "…" : "Sign in / Sign up"}

          </button>

          {authErr && <p className="text-red-400 text-sm">{authErr}</p>}

        </section>

      )}

      {token && (

        <section>

          <div className="flex gap-2 mb-4">

            <input

              className="flex-1 rounded border border-neutral-700 bg-neutral-900 p-2"

              placeholder="Case title"

              value={title}

              onChange={(e) => setTitle(e.target.value)}

            />

            <button

              onClick={() => void createCase()}

              disabled={!title.trim() || streaming}

              className="rounded bg-blue-600 px-4 font-medium hover:bg-blue-500 disabled:opacity-50"

            >

              New case

            </button>

          </div>

          <div className="space-y-2">

            {cases.map((c) => (

              <div key={c.id} className="rounded border border-neutral-800 p-3">

                <div className="font-medium">{c.title}</div>

                <div className="text-xs text-neutral-500">{c.status}</div>

                {c.status === "intake" && (

                  <button

                    onClick={() => void startDebate(c.id)}

                    disabled={streaming}

                    className="mt-2 rounded bg-neutral-800 px-3 py-1 text-sm hover:bg-neutral-700 disabled:opacity-50"

                  >

                    {streaming ? "debating…" : "Simulate"}

                  </button>

                )}

              </div>

            ))}

            {cases.length === 0 && <p className="text-sm text-neutral-500">No cases yet.</p>}

          </div>

          {turns.length > 0 && (

            <section className="mt-6 space-y-3">

              {turns.map((t) => (

                <div key={`${t.turn}-${t.role}`} className="rounded border border-neutral-800 p-3">

                  <div className="text-xs uppercase tracking-wide text-neutral-500">

                    Turn {t.turn} · {t.role}

                  </div>

                  <div className="mt-1 whitespace-pre-wrap text-sm">{t.content}</div>

                  {t.verdict && (

                    <div className="mt-2 rounded bg-neutral-900 p-2 text-sm">

                      <span className="font-mono">

                        {t.verdict.lower}%–{t.verdict.upper}%

                      </span>

                      <span className="ml-2 text-neutral-400">point: {t.verdict.point}%</span>

                      <div className="mt-1 text-xs text-amber-400">{t.verdict.note}</div>

                    </div>

                  )}

                </div>

              ))}

            </section>

          )}

          {streamErr && <p className="mt-3 text-sm text-red-400">{streamErr}</p>}

        </section>

      )}

    </main>

  );

}