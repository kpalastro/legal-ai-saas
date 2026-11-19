"use client";

/**
 * LexSim workspace: auth → case intake → uploads → live debate → attestation →
 * document review/export → deadlines → plans.
 *
 * The JWT is verified server-side by FastAPI; the browser only transports it.
 * Browser → Ollama is forbidden — everything goes through the API.
 */

import { useCallback, useEffect, useRef, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const GOTRUE_URL = process.env.NEXT_PUBLIC_GOTRUE_URL ?? "http://localhost:9999";
const TOKEN_KEY = "lexsim_token";
const REFRESH_KEY = "lexsim_refresh";

type Auth = { access: string; refresh: string };

type Turn = {
  turn: number;
  role: string;
  name: string;
  content: string;
  verdict?: {
    lower?: number;
    point?: number;
    upper?: number;
    raw?: string;
    note?: string;
    methodology_note?: string;
  };
};

type CaseRow = {
  id: string;
  title: string;
  jurisdiction: string;
  court?: string | null;
  cause_of_action: string;
  status: string;
  created_at?: string | null;
};

type CaseDetail = CaseRow & {
  description?: string | null;
  parties?: { name?: string; role?: string }[];
  issues?: string[];
  relief_sought?: string | null;
  case_number?: string | null;
  simulation_count?: number;
  document_count?: number;
  generated_document_count?: number;
  deadline_count?: number;
};

type SimulationRow = {
  id: string;
  status: string;
  outcome_prediction?: Turn["verdict"] | null;
  user_attestation: boolean;
  user_attested_at?: string | null;
  created_at?: string | null;
};

type UploadedDoc = {
  id: string;
  original_filename?: string | null;
  mime_type?: string | null;
  size_bytes?: number | null;
  extracted_preview?: string | null;
  uploaded_at?: string | null;
};

type Citation = {
  raw: string;
  status: "verified" | "unverified" | "flagged";
  source: string;
  url?: string | null;
  checked_at?: string | null;
  evidence?: string | null;
};

type GeneratedDoc = {
  id: string;
  doc_type: string;
  content?: string;
  citations?: Citation[];
  simulation_id?: string | null;
  user_reviewed?: boolean;
  exported?: boolean;
  export_blocked_reason?: string | null;
  gates?: {
    citations_all_verified: boolean;
    simulation_linked: boolean;
    simulation_attested: boolean;
    user_reviewed: boolean;
  };
  created_at?: string | null;
};

type Deadline = {
  id: string;
  trigger_doc_type: string;
  due_date: string;
  reminder_sent?: boolean;
  created_at?: string | null;
};

type Limitation = {
  due_date: string;
  years: number;
  provision: string;
  long_stop_date?: string | null;
  disclaimer: string;
};

type Plan = {
  id: string;
  label: string;
  amount_cents: number;
  currency: string;
  interval?: string | null;
};

type Me = {
  id: string;
  email: string;
  role: string;
  subscription_tier?: string | null;
};

function withAuth(token: string, init: RequestInit = {}): RequestInit {
  return {
    ...init,
    headers: { ...(init.headers ?? {}), Authorization: `Bearer ${token}` },
  };
}

function lines(value: string): string[] {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

function parties(value: string): { name: string; role: string }[] {
  return lines(value).map((line) => {
    const [name, role] = line.split("—").map((part) => part.trim());
    return { name: name ?? line, role: role ?? "party" };
  });
}

async function errorText(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    return typeof body.detail === "string" ? body.detail : `request failed (${response.status})`;
  } catch {
    return `request failed (${response.status})`;
  }
}

export default function Home() {
  const [auth, setAuth] = useState<Auth | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [cases, setCases] = useState<CaseRow[]>([]);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [simulations, setSimulations] = useState<SimulationRow[]>([]);
  const [uploads, setUploads] = useState<UploadedDoc[]>([]);
  const [generated, setGenerated] = useState<GeneratedDoc[]>([]);
  const [deadlines, setDeadlines] = useState<Deadline[]>([]);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [simulationId, setSimulationId] = useState<string | null>(null);
  const [tab, setTab] = useState<"overview" | "simulation" | "documents" | "deadlines">(
    "overview"
  );
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  // auth form
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [accepted, setAccepted] = useState(false);

  // new case
  const [showNewCase, setShowNewCase] = useState(false);
  const [title, setTitle] = useState("");
  const [jurisdiction, setJurisdiction] = useState("NSW Supreme Court");
  const [causeOfAction, setCauseOfAction] = useState("contract_breach");
  const [court, setCourt] = useState("NSW Supreme Court");
  const [caseNumber, setCaseNumber] = useState("");
  const [description, setDescription] = useState("");
  const [issuesText, setIssuesText] = useState("");
  const [partiesText, setPartiesText] = useState("");
  const [relief, setRelief] = useState("");

  // simulation
  const [intervention, setIntervention] = useState("");
  const abortRef = useRef<AbortController | null>(null);

  // uploads / docs
  const [file, setFile] = useState<File | null>(null);
  const [docType, setDocType] = useState("written_submissions");
  const [plaintiff, setPlaintiff] = useState("");
  const [defendant, setDefendant] = useState("");
  const [partyOpening, setPartyOpening] = useState("");
  const [factsText, setFactsText] = useState("");
  const [causesText, setCausesText] = useState("");
  const [activeDoc, setActiveDoc] = useState<GeneratedDoc | null>(null);

  // deadlines
  const [deadlineDoc, setDeadlineDoc] = useState("statement_of_claim");
  const [servedOn, setServedOn] = useState("");
  const [limitationCause, setLimitationCause] = useState("contract");
  const [accrualOn, setAccrualOn] = useState("");
  const [limitation, setLimitation] = useState<Limitation | null>(null);

  useEffect(() => {
    const saved = localStorage.getItem(TOKEN_KEY);
    const refresh = localStorage.getItem(REFRESH_KEY);
    if (saved && refresh) setAuth({ access: saved, refresh });
  }, []);

  const saveAuth = useCallback((next: Auth) => {
    setAuth(next);
    localStorage.setItem(TOKEN_KEY, next.access);
    localStorage.setItem(REFRESH_KEY, next.refresh);
  }, []);

  const clearAuth = useCallback(() => {
    setAuth(null);
    setMe(null);
    setCases([]);
    setSelectedId(null);
    setDetail(null);
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(REFRESH_KEY);
  }, []);

  const refreshAccess = useCallback(async (): Promise<string | null> => {
    if (!auth?.refresh) return null;
    const response = await fetch(`${GOTRUE_URL}/token?grant_type=refresh_token`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: auth.refresh }),
    });
    if (!response.ok) return null;
    const data = (await response.json()) as {
      access_token: string;
      refresh_token?: string;
    };
    const next = { access: data.access_token, refresh: data.refresh_token ?? auth.refresh };
    saveAuth(next);
    return next.access;
  }, [auth?.refresh, saveAuth]);

  const authFetch = useCallback(
    async (path: string, init: RequestInit = {}, retry = true): Promise<Response> => {
      if (!auth) throw new Error("not signed in");
      const headers: Record<string, string> = {
        ...((init.headers as Record<string, string>) ?? {}),
      };
      if (init.body && !(init.body instanceof FormData)) {
        headers["Content-Type"] = "application/json";
      }
      let response = await fetch(`${API_URL}${path}`, withAuth(auth.access, { ...init, headers }));
      if (response.status === 401 && retry) {
        const token = await refreshAccess();
        if (!token) {
          clearAuth();
          return response;
        }
        response = await fetch(`${API_URL}${path}`, withAuth(token, { ...init, headers }));
      }
      if (response.status === 401) clearAuth();
      return response;
    },
    [auth, refreshAccess, clearAuth]
  );

  const loadCases = useCallback(async () => {
    const response = await authFetch("/cases");
    if (response.ok) setCases((await response.json()) as CaseRow[]);
  }, [authFetch]);

  useEffect(() => {
    if (!auth) return;
    void (async () => {
      const meResponse = await authFetch("/users/me");
      if (meResponse.ok) setMe((await meResponse.json()) as Me);
      const plansResponse = await authFetch("/billing/plans");
      if (plansResponse.ok) setPlans((await plansResponse.json()) as Plan[]);
      await loadCases();
    })();
  }, [auth, authFetch, loadCases]);

  const refreshCaseCollections = useCallback(
    async (caseId: string) => {
      const [detailResponse, simsResponse, uploadsResponse, docsResponse, deadlinesResponse] =
        await Promise.all([
          authFetch(`/cases/${caseId}`),
          authFetch(`/cases/${caseId}/simulations`),
          authFetch(`/cases/${caseId}/documents`),
          authFetch(`/cases/${caseId}/generated-documents`),
          authFetch(`/cases/${caseId}/deadlines`),
        ]);
      if (detailResponse.ok) setDetail((await detailResponse.json()) as CaseDetail);
      if (simsResponse.ok) setSimulations((await simsResponse.json()) as SimulationRow[]);
      if (uploadsResponse.ok) setUploads((await uploadsResponse.json()) as UploadedDoc[]);
      if (docsResponse.ok) setGenerated((await docsResponse.json()) as GeneratedDoc[]);
      if (deadlinesResponse.ok) setDeadlines((await deadlinesResponse.json()) as Deadline[]);
    },
    [authFetch]
  );

  const openCase = useCallback(
    async (caseId: string) => {
      setSelectedId(caseId);
      setTab("overview");
      setTurns([]);
      setSimulationId(null);
      setActiveDoc(null);
      setError(null);
      await refreshCaseCollections(caseId);
    },
    [refreshCaseCollections]
  );

  async function signIn(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (!accepted) {
      setError("Please acknowledge the privacy and AI-assistance notice first.");
      return;
    }
    setBusy("auth");
    try {
      await fetch(`${GOTRUE_URL}/signup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const login = await fetch(`${GOTRUE_URL}/token?grant_type=password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (!login.ok) {
        setError(`sign in failed (${login.status})`);
        return;
      }
      const data = (await login.json()) as { access_token: string; refresh_token: string };
      saveAuth({ access: data.access_token, refresh: data.refresh_token });
      setNotice(null);
    } finally {
      setBusy(null);
    }
  }

  async function createCase(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy("case");
    try {
      const response = await authFetch("/cases", {
        method: "POST",
        body: JSON.stringify({
          title,
          jurisdiction,
          cause_of_action: causeOfAction,
          court,
          case_number: caseNumber || null,
          description: description || null,
          issues: lines(issuesText),
          parties: parties(partiesText),
          relief_sought: relief || null,
        }),
      });
      if (!response.ok) {
        setError(await errorText(response));
        return;
      }
      const created = (await response.json()) as { id: string };
      setShowNewCase(false);
      setTitle("");
      setDescription("");
      setIssuesText("");
      setPartiesText("");
      setRelief("");
      setCaseNumber("");
      await loadCases();
      await openCase(created.id);
    } finally {
      setBusy(null);
    }
  }

  async function startSimulation() {
    if (!selectedId) return;
    setError(null);
    setNotice(null);
    setTurns([]);
    setSimulationId(null);
    setBusy("simulation");
    const abort = new AbortController();
    abortRef.current = abort;
    const params = new URLSearchParams();
    for (const line of lines(intervention).slice(0, 10)) {
      params.append("intervention", line.slice(0, 2000));
    }
    const query = params.toString() ? `?${params.toString()}` : "";
    try {
      const response = await authFetch(`/cases/${selectedId}/simulate${query}`, {
        signal: abort.signal,
      });
      if (!response.ok || !response.body) {
        setError(await errorText(response));
        return;
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let event = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let index: number;
        while ((index = buffer.indexOf("\n\n")) >= 0) {
          const frame = buffer.slice(0, index);
          buffer = buffer.slice(index + 2);
          let data: string | null = null;
          for (const line of frame.split("\n")) {
            if (line.startsWith("event: ")) event = line.slice(7).trim();
            else if (line.startsWith("data: ")) data = line.slice(6);
          }
          if (data == null) continue;
          const payload = JSON.parse(data) as Record<string, unknown>;
          if (event === "turn") {
            setTurns((previous) => [...previous, payload as unknown as Turn]);
          } else if (event === "done") {
            const id = payload.simulation_id;
            setSimulationId(typeof id === "string" ? id : null);
            setNotice("Simulation complete. Review it, then attest before generating documents.");
          } else if (event === "error") {
            setError(
              typeof payload.detail === "string" ? payload.detail : "simulation failed"
            );
          }
        }
      }
    } catch {
      if (!abort.signal.aborted) setError("simulation stream failed");
    } finally {
      setBusy(null);
      abortRef.current = null;
      await refreshCaseCollections(selectedId);
    }
  }

  async function attestSimulation(id: string) {
    setBusy(`attest-sim-${id}`);
    try {
      const response = await authFetch(`/simulations/${id}/attest`, {
        method: "POST",
        body: JSON.stringify({ user_attestation: true }),
      });
      if (!response.ok) {
        setError(await errorText(response));
        return;
      }
      setNotice("Simulation attested. You can now review and export linked documents.");
      if (selectedId) await refreshCaseCollections(selectedId);
    } finally {
      setBusy(null);
    }
  }

  async function uploadDocument(event: React.FormEvent) {
    event.preventDefault();
    if (!selectedId || !file) return;
    setError(null);
    setBusy("upload");
    try {
      const form = new FormData();
      form.append("file", file);
      const response = await authFetch(`/cases/${selectedId}/documents`, {
        method: "POST",
        body: form,
      });
      if (!response.ok) {
        setError(await errorText(response));
        return;
      }
      setFile(null);
      setNotice("Document uploaded and text extracted for grounding.");
      await refreshCaseCollections(selectedId);
    } finally {
      setBusy(null);
    }
  }

  async function generateDocument(event: React.FormEvent) {
    event.preventDefault();
    if (!selectedId) return;
    setError(null);
    setBusy("generate");
    try {
      const body = {
        case_id: selectedId,
        doc_type: docType,
        jurisdiction: detail?.jurisdiction ?? "NSW Supreme Court",
        fields: {
          plaintiff: plaintiff || "Plaintiff",
          defendant: defendant || "Defendant",
          party_opening: partyOpening,
          facts: lines(factsText),
          causes_of_action: lines(causesText),
          submissions: lines(factsText),
          orders: relief || "Orders sought as set out above.",
        },
      };
      const response = await authFetch("/documents/generate", {
        method: "POST",
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        setError(await errorText(response));
        return;
      }
      const doc = (await response.json()) as GeneratedDoc;
      setActiveDoc(doc);
      setNotice("Draft generated. Verify every citation, then attest the document.");
      await refreshCaseCollections(selectedId);
    } finally {
      setBusy(null);
    }
  }

  async function attestDocument(id: string) {
    setBusy(`attest-doc-${id}`);
    try {
      const response = await authFetch(`/documents/${id}/attest`, {
        method: "POST",
        body: JSON.stringify({ user_reviewed: true }),
      });
      if (!response.ok) {
        setError(await errorText(response));
        return;
      }
      setNotice("Document attested. Export is now gated only by the simulation attestation.");
      if (selectedId) await refreshCaseCollections(selectedId);
    } finally {
      setBusy(null);
    }
  }

  async function exportDocument(id: string, format: "txt" | "docx" | "pdf") {
    setError(null);
    setBusy(`export-${id}-${format}`);
    try {
      const response = await authFetch(`/documents/${id}/export?format=${format}`);
      if (!response.ok) {
        setError(await errorText(response));
        return;
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `lexsim-${id.slice(0, 8)}.${format}`;
      anchor.click();
      URL.revokeObjectURL(url);
      if (selectedId) await refreshCaseCollections(selectedId);
    } finally {
      setBusy(null);
    }
  }

  async function storeDeadline(event: React.FormEvent) {
    event.preventDefault();
    if (!selectedId) return;
    setError(null);
    setBusy("deadline");
    try {
      const response = await authFetch(`/cases/${selectedId}/deadlines`, {
        method: "POST",
        body: JSON.stringify({
          doc_type: deadlineDoc,
          jurisdiction: detail?.jurisdiction ?? "NSW Supreme Court",
          served_on: servedOn || null,
        }),
      });
      if (!response.ok) {
        setError(await errorText(response));
        return;
      }
      await refreshCaseCollections(selectedId);
    } finally {
      setBusy(null);
    }
  }

  async function computeLimitation(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy("limitation");
    try {
      const response = await authFetch("/limitations/compute", {
        method: "POST",
        body: JSON.stringify({
          cause_of_action: limitationCause,
          jurisdiction: detail?.jurisdiction ?? "NSW Supreme Court",
          accrual_on: accrualOn || null,
        }),
      });
      if (!response.ok) {
        setError(await errorText(response));
        setLimitation(null);
        return;
      }
      setLimitation((await response.json()) as Limitation);
    } finally {
      setBusy(null);
    }
  }

  async function checkout(plan: string) {
    setError(null);
    setNotice(null);
    setBusy(`plan-${plan}`);
    try {
      const response = await authFetch("/billing/checkout", {
        method: "POST",
        body: JSON.stringify({ plan }),
      });
      if (!response.ok) {
        setError(await errorText(response));
        return;
      }
      const session = (await response.json()) as { url?: string };
      if (session.url) window.location.href = session.url;
    } finally {
      setBusy(null);
    }
  }

  // ===== auth screen =====
  if (!auth) {
    return (
      <main className="min-h-screen p-6 md:p-12 max-w-2xl mx-auto">
        <h1 className="text-2xl font-bold mb-1">LexSim AI</h1>
        <p className="text-sm text-neutral-400 mb-6">
          Multi-agent legal debate simulation · simulation and preparation only — not legal advice.
        </p>
        <form onSubmit={signIn} className="space-y-3" aria-label="Sign in">
          <label className="block text-sm">
            Email
            <input
              className="mt-1 w-full rounded border border-neutral-700 bg-neutral-900 p-2"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </label>
          <label className="block text-sm">
            Password
            <input
              className="mt-1 w-full rounded border border-neutral-700 bg-neutral-900 p-2"
              type="password"
              autoComplete="current-password"
              minLength={8}
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          <div className="rounded border border-amber-900 bg-amber-950/30 p-3 text-xs text-amber-200">
            <p className="font-medium">Before you continue</p>
            <p className="mt-1">
              Case content is processed by a private model instance. AI analysis may not be
              privileged; do not upload confidential client communications without legal advice.
              Generated documents must be reviewed and every citation verified before filing
              (NSW SC Gen 23).
            </p>
            <label className="mt-2 flex items-start gap-2">
              <input
                type="checkbox"
                checked={accepted}
                onChange={(event) => setAccepted(event.target.checked)}
              />
              <span>I understand and agree to review all AI-assisted output.</span>
            </label>
          </div>
          <button
            type="submit"
            disabled={busy === "auth"}
            className="w-full rounded bg-blue-600 p-2 font-medium hover:bg-blue-500 disabled:opacity-50"
          >
            {busy === "auth" ? "Signing in…" : "Sign in / create account"}
          </button>
          {error && (
            <p role="alert" className="text-sm text-red-400">
              {error}
            </p>
          )}
        </form>
      </main>
    );
  }

  // ===== workspace =====
  return (
    <main className="min-h-screen">
      <header className="border-b border-neutral-800 px-4 py-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-lg font-bold">LexSim AI</h1>
          <p className="text-xs text-neutral-400">
            Simulation and preparation only — not legal advice.
          </p>
        </div>
        <div className="flex items-center gap-3 text-xs text-neutral-400">
          {me && (
            <span>
              {me.email} · {me.role}
              {me.subscription_tier ? ` · ${me.subscription_tier}` : ""}
            </span>
          )}
          <button
            onClick={() => {
              abortRef.current?.abort();
              clearAuth();
            }}
            className="rounded border border-neutral-700 px-3 py-1 hover:bg-neutral-800"
          >
            Sign out
          </button>
        </div>
      </header>

      {(error || notice) && (
        <div className="px-4 py-2 text-sm" aria-live="polite">
          {error && <p className="text-red-400">{error}</p>}
          {notice && <p className="text-emerald-400">{notice}</p>}
        </div>
      )}

      <div className="grid gap-4 p-4 md:grid-cols-[340px_1fr]">
        <aside className="space-y-4">
          <section className="rounded border border-neutral-800">
            <div className="flex items-center justify-between border-b border-neutral-800 p-3">
              <h2 className="font-semibold text-sm">Your matters</h2>
              <button
                onClick={() => setShowNewCase((value) => !value)}
                className="rounded bg-neutral-800 px-2 py-1 text-xs hover:bg-neutral-700"
              >
                {showNewCase ? "Cancel" : "New case"}
              </button>
            </div>
            <ul className="divide-y divide-neutral-900">
              {cases.map((row) => (
                <li key={row.id}>
                  <button
                    onClick={() => void openCase(row.id)}
                    className={`w-full p-3 text-left hover:bg-neutral-900 ${
                      selectedId === row.id ? "bg-neutral-900" : ""
                    }`}
                  >
                    <span className="block text-sm font-medium">{row.title}</span>
                    <span className="block text-xs text-neutral-500">
                      {row.court || row.jurisdiction} · {row.status}
                    </span>
                  </button>
                </li>
              ))}
              {cases.length === 0 && (
                <li className="p-3 text-sm text-neutral-500">No matters yet.</li>
              )}
            </ul>
          </section>

          {showNewCase && (
            <form onSubmit={createCase} className="space-y-2 rounded border border-neutral-800 p-3">
              <h2 className="text-sm font-semibold">New case intake</h2>
              <label className="block text-xs">
                Title
                <input
                  className="mt-1 w-full rounded border border-neutral-700 bg-neutral-900 p-2"
                  required
                  minLength={3}
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                />
              </label>
              <label className="block text-xs">
                Court / jurisdiction
                <input
                  className="mt-1 w-full rounded border border-neutral-700 bg-neutral-900 p-2"
                  value={court}
                  onChange={(event) => {
                    setCourt(event.target.value);
                    setJurisdiction(event.target.value);
                  }}
                />
              </label>
              <label className="block text-xs">
                Court file number
                <input
                  className="mt-1 w-full rounded border border-neutral-700 bg-neutral-900 p-2"
                  value={caseNumber}
                  onChange={(event) => setCaseNumber(event.target.value)}
                />
              </label>
              <label className="block text-xs">
                Cause of action
                <input
                  className="mt-1 w-full rounded border border-neutral-700 bg-neutral-900 p-2"
                  value={causeOfAction}
                  onChange={(event) => setCauseOfAction(event.target.value)}
                />
              </label>
              <label className="block text-xs">
                Facts
                <textarea
                  className="mt-1 h-24 w-full rounded border border-neutral-700 bg-neutral-900 p-2"
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                />
              </label>
              <label className="block text-xs">
                Issues (one per line)
                <textarea
                  className="mt-1 h-16 w-full rounded border border-neutral-700 bg-neutral-900 p-2"
                  value={issuesText}
                  onChange={(event) => setIssuesText(event.target.value)}
                />
              </label>
              <label className="block text-xs">
                Parties (Name — role, one per line)
                <textarea
                  className="mt-1 h-16 w-full rounded border border-neutral-700 bg-neutral-900 p-2"
                  value={partiesText}
                  onChange={(event) => setPartiesText(event.target.value)}
                />
              </label>
              <label className="block text-xs">
                Relief sought
                <textarea
                  className="mt-1 h-16 w-full rounded border border-neutral-700 bg-neutral-900 p-2"
                  value={relief}
                  onChange={(event) => setRelief(event.target.value)}
                />
              </label>
              <button
                type="submit"
                disabled={busy === "case"}
                className="w-full rounded bg-blue-600 p-2 text-sm font-medium hover:bg-blue-500 disabled:opacity-50"
              >
                {busy === "case" ? "Creating…" : "Create matter"}
              </button>
            </form>
          )}

          {plans.length > 0 && (
            <section className="rounded border border-neutral-800 p-3">
              <h2 className="text-sm font-semibold">Plans</h2>
              <ul className="mt-2 space-y-2">
                {plans.map((plan) => (
                  <li key={plan.id} className="flex items-center justify-between gap-2 text-xs">
                    <span>
                      {plan.label} · ${(plan.amount_cents / 100).toFixed(0)}
                      {plan.interval ? "/mo" : ""}
                    </span>
                    <button
                      onClick={() => void checkout(plan.id)}
                      disabled={busy === `plan-${plan.id}`}
                      className="rounded border border-neutral-700 px-2 py-1 hover:bg-neutral-800 disabled:opacity-50"
                    >
                      Buy
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </aside>

        <section className="min-w-0">
          {!selectedId || !detail ? (
            <div className="rounded border border-neutral-800 p-6 text-sm text-neutral-400">
              Select a matter or create one to begin intake, simulation, documents and deadlines.
            </div>
          ) : (
            <>
              <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h2 className="text-xl font-semibold">{detail.title}</h2>
                  <p className="text-xs text-neutral-500">
                    {detail.court || detail.jurisdiction} · {detail.cause_of_action} ·{" "}
                    {detail.status}
                    {detail.case_number ? ` · ${detail.case_number}` : ""}
                  </p>
                </div>
                <nav className="flex gap-1" aria-label="Case sections">
                  {(["overview", "simulation", "documents", "deadlines"] as const).map((name) => (
                    <button
                      key={name}
                      onClick={() => setTab(name)}
                      className={`rounded px-3 py-1 text-xs capitalize ${
                        tab === name ? "bg-blue-600" : "bg-neutral-800 hover:bg-neutral-700"
                      }`}
                    >
                      {name}
                    </button>
                  ))}
                </nav>
              </div>

              {tab === "overview" && (
                <div className="space-y-4">
                  <section className="rounded border border-neutral-800 p-4">
                    <h3 className="text-sm font-semibold">Facts</h3>
                    <p className="mt-1 whitespace-pre-wrap text-sm text-neutral-300">
                      {detail.description || "No facts recorded."}
                    </p>
                  </section>
                  <div className="grid gap-4 md:grid-cols-2">
                    <section className="rounded border border-neutral-800 p-4 text-sm">
                      <h3 className="font-semibold">Issues</h3>
                      <ul className="mt-1 list-disc pl-5 text-neutral-300">
                        {(detail.issues ?? []).map((issue, index) => (
                          <li key={`${issue}-${index}`}>{issue}</li>
                        ))}
                        {(detail.issues ?? []).length === 0 && <li>None recorded.</li>}
                      </ul>
                    </section>
                    <section className="rounded border border-neutral-800 p-4 text-sm">
                      <h3 className="font-semibold">Parties</h3>
                      <ul className="mt-1 list-disc pl-5 text-neutral-300">
                        {(detail.parties ?? []).map((party, index) => (
                          <li key={`${party.name}-${index}`}>
                            {party.name} — {party.role}
                          </li>
                        ))}
                        {(detail.parties ?? []).length === 0 && <li>None recorded.</li>}
                      </ul>
                    </section>
                  </div>
                  <section className="rounded border border-neutral-800 p-4 text-sm">
                    <h3 className="font-semibold">Relief sought</h3>
                    <p className="mt-1 text-neutral-300">{detail.relief_sought || "Not recorded."}</p>
                  </section>
                  <div className="grid grid-cols-2 gap-2 text-center md:grid-cols-4">
                    {[
                      ["Simulations", detail.simulation_count ?? 0],
                      ["Uploads", detail.document_count ?? 0],
                      ["Drafts", detail.generated_document_count ?? 0],
                      ["Deadlines", detail.deadline_count ?? 0],
                    ].map(([label, value]) => (
                      <div key={String(label)} className="rounded border border-neutral-800 p-3">
                        <div className="text-lg font-semibold">{value}</div>
                        <div className="text-xs text-neutral-500">{label}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {tab === "simulation" && (
                <div className="space-y-4">
                  <section className="rounded border border-neutral-800 p-4">
                    <h3 className="text-sm font-semibold">Run the 9-turn simulation</h3>
                    <p className="mt-1 text-xs text-neutral-500">
                      The engine reads your intake, issues, parties and extracted uploads, and
                      carries the transcript forward each turn.
                    </p>
                    <label className="mt-3 block text-xs">
                      Optional instructions to both advocates (one per line)
                      <textarea
                        className="mt-1 h-16 w-full rounded border border-neutral-700 bg-neutral-900 p-2"
                        value={intervention}
                        onChange={(event) => setIntervention(event.target.value)}
                      />
                    </label>
                    <button
                      onClick={() => void startSimulation()}
                      disabled={busy === "simulation"}
                      className="mt-3 rounded bg-blue-600 px-4 py-2 text-sm font-medium hover:bg-blue-500 disabled:opacity-50"
                    >
                      {busy === "simulation" ? "Debating…" : "Run simulation"}
                    </button>
                  </section>

                  {turns.map((turn) => (
                    <article key={`${turn.turn}-${turn.role}`} className="rounded border border-neutral-800 p-3">
                      <div className="text-xs uppercase tracking-wide text-neutral-500">
                        Turn {turn.turn} · {turn.role} · {turn.name}
                      </div>
                      {turn.verdict ? (
                        <div className="mt-2 rounded bg-neutral-900 p-3 text-sm">
                          {typeof turn.verdict.lower === "number" ? (
                            <p className="font-mono">
                              {turn.verdict.lower}%–{turn.verdict.upper}% · point{" "}
                              {turn.verdict.point}%
                            </p>
                          ) : (
                            <p className="whitespace-pre-wrap">{turn.verdict.raw}</p>
                          )}
                          <p className="mt-1 text-xs text-amber-400">
                            {turn.verdict.methodology_note ?? turn.verdict.note}
                          </p>
                        </div>
                      ) : (
                        <p className="mt-1 whitespace-pre-wrap text-sm">{turn.content}</p>
                      )}
                    </article>
                  ))}

                  <section className="rounded border border-neutral-800 p-4">
                    <h3 className="text-sm font-semibold">Simulation history</h3>
                    <ul className="mt-2 space-y-2">
                      {simulations.map((simulation) => (
                        <li
                          key={simulation.id}
                          className="flex flex-wrap items-center justify-between gap-2 rounded bg-neutral-900 p-2 text-xs"
                        >
                          <span>
                            {simulation.created_at ?? "—"} · {simulation.status} ·{" "}
                            {simulation.user_attestation ? "attested" : "not attested"}
                          </span>
                          {!simulation.user_attestation && (
                            <button
                              onClick={() => void attestSimulation(simulation.id)}
                              disabled={busy === `attest-sim-${simulation.id}`}
                              className="rounded border border-emerald-700 px-2 py-1 text-emerald-300 hover:bg-emerald-950 disabled:opacity-50"
                            >
                              Attest (SC Gen 23)
                            </button>
                          )}
                        </li>
                      ))}
                      {simulations.length === 0 && (
                        <li className="text-xs text-neutral-500">No simulations yet.</li>
                      )}
                    </ul>
                    {simulationId && (
                      <p className="mt-2 text-xs text-neutral-500">Latest id: {simulationId}</p>
                    )}
                  </section>
                </div>
              )}

              {tab === "documents" && (
                <div className="space-y-4">
                  <section className="rounded border border-neutral-800 p-4">
                    <h3 className="text-sm font-semibold">Upload evidence</h3>
                    <form onSubmit={uploadDocument} className="mt-2 flex flex-wrap items-center gap-2">
                      <input
                        type="file"
                        accept=".pdf,.docx,.txt,.md,.csv"
                        onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                        className="text-xs"
                        aria-label="Upload case document"
                      />
                      <button
                        type="submit"
                        disabled={!file || busy === "upload"}
                        className="rounded bg-neutral-800 px-3 py-1 text-xs hover:bg-neutral-700 disabled:opacity-50"
                      >
                        {busy === "upload" ? "Uploading…" : "Upload"}
                      </button>
                    </form>
                    <ul className="mt-3 space-y-2">
                      {uploads.map((upload) => (
                        <li key={upload.id} className="rounded bg-neutral-900 p-2 text-xs">
                          <div className="font-medium">{upload.original_filename}</div>
                          <div className="text-neutral-500">
                            {upload.mime_type} · {upload.size_bytes ?? 0} bytes
                          </div>
                          {upload.extracted_preview && (
                            <p className="mt-1 line-clamp-3 text-neutral-400">
                              {upload.extracted_preview}
                            </p>
                          )}
                        </li>
                      ))}
                      {uploads.length === 0 && (
                        <li className="text-xs text-neutral-500">No uploads yet.</li>
                      )}
                    </ul>
                  </section>

                  <form onSubmit={generateDocument} className="space-y-2 rounded border border-neutral-800 p-4">
                    <h3 className="text-sm font-semibold">Generate a document</h3>
                    <p className="text-xs text-neutral-500">
                      Allowed: statement of claim, defence, written submissions, chronology,
                      court correspondence. Affidavits and witness statements are blocked.
                    </p>
                    <label className="block text-xs">
                      Document type
                      <select
                        className="mt-1 w-full rounded border border-neutral-700 bg-neutral-900 p-2"
                        value={docType}
                        onChange={(event) => setDocType(event.target.value)}
                      >
                        <option value="statement_of_claim">Statement of claim</option>
                        <option value="defence">Defence</option>
                        <option value="written_submissions">Written submissions</option>
                        <option value="chronology">Chronology</option>
                        <option value="court_correspondence">Court correspondence</option>
                      </select>
                    </label>
                    <div className="grid gap-2 md:grid-cols-2">
                      <label className="block text-xs">
                        Plaintiff
                        <input
                          className="mt-1 w-full rounded border border-neutral-700 bg-neutral-900 p-2"
                          value={plaintiff}
                          onChange={(event) => setPlaintiff(event.target.value)}
                        />
                      </label>
                      <label className="block text-xs">
                        Defendant
                        <input
                          className="mt-1 w-full rounded border border-neutral-700 bg-neutral-900 p-2"
                          value={defendant}
                          onChange={(event) => setDefendant(event.target.value)}
                        />
                      </label>
                    </div>
                    <label className="block text-xs">
                      Opening / body
                      <textarea
                        className="mt-1 h-20 w-full rounded border border-neutral-700 bg-neutral-900 p-2"
                        value={partyOpening}
                        onChange={(event) => setPartyOpening(event.target.value)}
                      />
                    </label>
                    <label className="block text-xs">
                      Facts / submissions (one per line)
                      <textarea
                        className="mt-1 h-20 w-full rounded border border-neutral-700 bg-neutral-900 p-2"
                        value={factsText}
                        onChange={(event) => setFactsText(event.target.value)}
                      />
                    </label>
                    <label className="block text-xs">
                      Causes of action (one per line)
                      <textarea
                        className="mt-1 h-16 w-full rounded border border-neutral-700 bg-neutral-900 p-2"
                        value={causesText}
                        onChange={(event) => setCausesText(event.target.value)}
                      />
                    </label>
                    <button
                      type="submit"
                      disabled={busy === "generate"}
                      className="rounded bg-blue-600 px-4 py-2 text-sm font-medium hover:bg-blue-500 disabled:opacity-50"
                    >
                      {busy === "generate" ? "Generating…" : "Generate draft"}
                    </button>
                  </form>

                  {activeDoc && (
                    <section className="rounded border border-neutral-800 p-4">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <h3 className="text-sm font-semibold">Draft {activeDoc.doc_type}</h3>
                        <div className="flex flex-wrap gap-2">
                          <button
                            onClick={() => void attestDocument(activeDoc.id)}
                            disabled={busy === `attest-doc-${activeDoc.id}`}
                            className="rounded border border-emerald-700 px-2 py-1 text-xs text-emerald-300 hover:bg-emerald-950 disabled:opacity-50"
                          >
                            Attest I reviewed it
                          </button>
                          {(["txt", "docx", "pdf"] as const).map((format) => (
                            <button
                              key={format}
                              onClick={() => void exportDocument(activeDoc.id, format)}
                              disabled={busy === `export-${activeDoc.id}-${format}`}
                              className="rounded border border-neutral-700 px-2 py-1 text-xs hover:bg-neutral-800 disabled:opacity-50"
                            >
                              Export {format.toUpperCase()}
                            </button>
                          ))}
                        </div>
                      </div>
                      {activeDoc.gates && (
                        <ul className="mt-2 grid gap-1 text-xs text-neutral-400 md:grid-cols-2">
                          <li>
                            Citations verified:{" "}
                            {activeDoc.gates.citations_all_verified ? "yes" : "no"}
                          </li>
                          <li>
                            Simulation linked: {activeDoc.gates.simulation_linked ? "yes" : "no"}
                          </li>
                          <li>
                            Simulation attested:{" "}
                            {activeDoc.gates.simulation_attested ? "yes" : "no"}
                          </li>
                          <li>Document reviewed: {activeDoc.gates.user_reviewed ? "yes" : "no"}</li>
                        </ul>
                      )}
                      <div className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap rounded bg-neutral-950 p-3 text-xs">
                        {activeDoc.content}
                      </div>
                      {(activeDoc.citations ?? []).length > 0 && (
                        <ul className="mt-2 space-y-1 text-xs">
                          {(activeDoc.citations ?? []).map((citation) => (
                            <li key={citation.raw} className="rounded bg-neutral-900 p-2">
                              <span
                                className={
                                  citation.status === "verified"
                                    ? "text-emerald-400"
                                    : citation.status === "flagged"
                                      ? "text-red-400"
                                      : "text-amber-400"
                                }
                              >
                                {citation.status.toUpperCase()}
                              </span>{" "}
                              {citation.raw}
                              {citation.evidence && (
                                <p className="mt-1 text-neutral-500">{citation.evidence}</p>
                              )}
                            </li>
                          ))}
                        </ul>
                      )}
                    </section>
                  )}

                  <section className="rounded border border-neutral-800 p-4">
                    <h3 className="text-sm font-semibold">Generated documents</h3>
                    <ul className="mt-2 space-y-2">
                      {generated.map((doc) => (
                        <li key={doc.id} className="flex flex-wrap items-center justify-between gap-2 rounded bg-neutral-900 p-2 text-xs">
                          <span>
                            {doc.doc_type} · {doc.exported ? "exported" : "not exported"} ·{" "}
                            {doc.user_reviewed ? "reviewed" : "not reviewed"}
                          </span>
                          <button
                            onClick={() => setActiveDoc(doc)}
                            className="rounded border border-neutral-700 px-2 py-1 hover:bg-neutral-800"
                          >
                            Open
                          </button>
                        </li>
                      ))}
                      {generated.length === 0 && (
                        <li className="text-xs text-neutral-500">No generated documents yet.</li>
                      )}
                    </ul>
                  </section>
                </div>
              )}

              {tab === "deadlines" && (
                <div className="space-y-4">
                  <form onSubmit={storeDeadline} className="space-y-2 rounded border border-neutral-800 p-4">
                    <h3 className="text-sm font-semibold">Response deadline</h3>
                    <div className="grid gap-2 md:grid-cols-2">
                      <label className="block text-xs">
                        Trigger document
                        <select
                          className="mt-1 w-full rounded border border-neutral-700 bg-neutral-900 p-2"
                          value={deadlineDoc}
                          onChange={(event) => setDeadlineDoc(event.target.value)}
                        >
                          <option value="statement_of_claim">Statement of claim</option>
                          <option value="court_correspondence">Court correspondence</option>
                          <option value="defence">Defence</option>
                        </select>
                      </label>
                      <label className="block text-xs">
                        Served on
                        <input
                          type="date"
                          className="mt-1 w-full rounded border border-neutral-700 bg-neutral-900 p-2"
                          value={servedOn}
                          onChange={(event) => setServedOn(event.target.value)}
                        />
                      </label>
                    </div>
                    <button
                      type="submit"
                      disabled={busy === "deadline"}
                      className="rounded bg-blue-600 px-4 py-2 text-sm font-medium hover:bg-blue-500 disabled:opacity-50"
                    >
                      Compute & save
                    </button>
                  </form>

                  <ul className="space-y-2">
                    {deadlines.map((deadline) => (
                      <li key={deadline.id} className="rounded border border-neutral-800 p-3 text-sm">
                        {deadline.trigger_doc_type} → due {deadline.due_date}
                      </li>
                    ))}
                    {deadlines.length === 0 && (
                      <li className="text-xs text-neutral-500">No deadlines saved.</li>
                    )}
                  </ul>

                  <form onSubmit={computeLimitation} className="space-y-2 rounded border border-neutral-800 p-4">
                    <h3 className="text-sm font-semibold">Limitation period (NSW)</h3>
                    <div className="grid gap-2 md:grid-cols-2">
                      <label className="block text-xs">
                        Cause of action
                        <select
                          className="mt-1 w-full rounded border border-neutral-700 bg-neutral-900 p-2"
                          value={limitationCause}
                          onChange={(event) => setLimitationCause(event.target.value)}
                        >
                          <option value="contract">Contract</option>
                          <option value="tort">Tort</option>
                          <option value="personal_injury">Personal injury</option>
                        </select>
                      </label>
                      <label className="block text-xs">
                        Accrued on
                        <input
                          type="date"
                          className="mt-1 w-full rounded border border-neutral-700 bg-neutral-900 p-2"
                          value={accrualOn}
                          onChange={(event) => setAccrualOn(event.target.value)}
                        />
                      </label>
                    </div>
                    <button
                      type="submit"
                      disabled={busy === "limitation"}
                      className="rounded bg-blue-600 px-4 py-2 text-sm font-medium hover:bg-blue-500 disabled:opacity-50"
                    >
                      Compute limitation
                    </button>
                    {limitation && (
                      <div className="rounded bg-neutral-900 p-3 text-xs">
                        <p className="font-mono">Due: {limitation.due_date}</p>
                        <p className="text-neutral-400">{limitation.provision}</p>
                        {limitation.long_stop_date && (
                          <p className="text-neutral-400">
                            Long-stop: {limitation.long_stop_date}
                          </p>
                        )}
                        <p className="mt-1 text-amber-400">{limitation.disclaimer}</p>
                      </div>
                    )}
                  </form>
                </div>
              )}
            </>
          )}
        </section>
      </div>
    </main>
  );
}
