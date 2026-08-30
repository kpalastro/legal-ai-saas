# LexSim AI — System Architecture

> **⚠️ DEPRECATED (30 Aug 2026) — READ TECH_STACK.md v2 FIRST.**
> This document is superseded by `TECH_STACK.md` (v2) and `TEST_PLAN.md`. Known-stale content that MUST NOT be built against:
> - `verify_citations()` pseudocode (~line 359) targets **AustLII** — banned for all AI/programmatic use. Citation verification = FRL OData API + NSW Caselaw + JADE only (see TECH_STACK.md).
> - Clerk.dev auth + `clerk_user_id` DDL — replaced by **Supabase Auth** (`id UUID REFERENCES auth.users(id)`); the `auth.uid()` RLS policy only works with the Supabase model.
> - Celery → **arq**; WebSocket/Kong → **SSE**; self-hosted DeepSeek-V3 on 1×A100 → **Bedrock Sydney gpt-oss-120b** API.
> Kept for historical context only. Sources of truth: `TECH_STACK.md`, `TEST_PLAN.md`, `COMPLIANCE_CHECKLIST.md` (forthcoming).

## Overview
Multi-agent legal debate simulation SaaS for Australian self-represented litigants and solo practitioners.

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            CLIENT LAYER                                      │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────────┐  │
│  │   Next.js 14     │  │   Mobile App     │  │   Admin Dashboard        │  │
│  │   (Web App)      │  │   (React Native) │  │   (Internal)             │  │
│  │   - Auth         │  │   - Case intake  │  │   - User management      │  │
│  │   - Case intake  │  │   - Simulations  │  │   - Billing              │  │
│  │   - Dashboard    │  │   - Documents    │  │   - Analytics            │  │
│  │   - Documents    │  │                  │  │                          │  │
│  └──────────────────┘  └──────────────────┘  └──────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ HTTPS (REST/GraphQL)
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            API GATEWAY                                       │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  Kong / AWS API Gateway                                              │  │
│  │  - Rate limiting (100 req/min per user)                              │  │
│  │  - JWT validation (Auth0/Clerk)                                      │  │
│  │  - Request routing                                                   │  │
│  │  - CORS, WAF rules                                                   │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ Internal VPC
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         APPLICATION LAYER                                    │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────────┐  │
│  │   FastAPI        │  │   Celery Workers │  │   WebSocket Server       │  │
│  │   (Backend)      │  │   (Async Tasks)  │  │   (Live Simulation)      │  │
│  │                  │  │                  │  │                          │  │
│  │  - REST API      │  │  - Simulations   │  │  - Debate streaming      │  │
│  │  - Auth          │  │  - Document gen  │  │  - Progress updates      │  │
│  │  - CRUD          │  │  - Citation check│  │  - Real-time chat        │  │
│  │  - Webhooks      │  │  - Email/SMS     │  │                          │  │
│  └──────────────────┘  └──────────────────┘  └──────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    │               │               │
                    ▼               ▼               ▼
┌──────────────────────┐ ┌──────────────────┐ ┌────────────────────────────┐
│   PostgreSQL         │ │   Redis          │ │   S3 (AWS)                 │
│   (Supabase)         │ │   (ElastiCache)  │ │   or MinIO                 │
│                      │ │                  │ │                            │
│  - Users (RLS)       │ │  - Cache         │ │  - Uploaded documents      │
│  - Cases             │ │  - Sessions      │ │  - Generated PDFs          │
│  - Simulations       │ │  - Celery queue  │ │  - Audit logs              │
│  - Documents         │ │  - Rate limits   │ │  - Model artifacts         │
│  - Deadlines         │ │                  │ │                            │
└──────────────────────┘ └──────────────────┘ └────────────────────────────┘
                                    │
                                    │ gRPC / HTTP
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      AI ORCHESTRATION LAYER                                  │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │   Agent Orchestrator (Python)                                        │  │
│  │                                                                      │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │  │
│  │  │  USER_      │  │  OPPONENT   │  │  JUDGE      │  │  VERIFIER   │ │  │
│  │  │  ADVOCATE   │  │  AGENT      │  │  AGENT      │  │  AGENT      │ │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘ │  │
│  │                                                                      │  │
│  │  - Debate state machine (7-turn protocol)                            │  │
│  │  - Agent prompt management                                           │  │
│  │  - Citation extraction & verification pipeline                       │  │
│  │  - Document generation (Jinja2 templates)                            │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ HTTP / gRPC
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      INFERENCE LAYER                                         │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────────┐  │
│  │   SGLang Server  │  │   vLLM Server    │  │   Embedding Service      │  │
│  │   (Primary)      │  │   (Fallback)     │  │   (BGE-M3)               │  │
│  │                  │  │                  │  │                          │  │
│  │  - DeepSeek-V3   │  │  - Llama-3.1-70B │  │  - AustLII RAG           │  │
│  │  - MLA arch      │  │  - GQA arch      │  │  - Semantic search       │  │
│  │  - RadixAttention│  │  - PagedAttention│  │  - Case similarity       │  │
│  └──────────────────┘  └──────────────────┘  └──────────────────────────┘  │
│                                                                              │
│  Hosted on: RunPod A100 ($1.43/hr) or Lambda Labs H100                       │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ HTTPS
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      EXTERNAL APIs                                           │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────────┐  │
│  │   AustLII        │  │   JADE.io        │  │   Stripe                 │  │
│  │   (Case Law)     │  │   (Alt Database) │  │   (Payments)             │  │
│  └──────────────────┘  └──────────────────┘  └──────────────────────────┘  │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────────┐  │
│  │   SendGrid       │  │   Twilio         │  │   Auth0/Clerk            │  │
│  │   (Email)        │  │   (SMS)          │  │   (Auth)                 │  │
│  └──────────────────┘  └──────────────────┘  └──────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Component Specifications

### 1. Frontend (Next.js 14)

**Tech Stack:**
- TypeScript 5.x
- Tailwind CSS + shadcn/ui
- React Query (data fetching)
- Zustand (state management)
- React Hook Form + Zod (validation)

**Key Pages:**
```
/                   → Landing page
/login              → Auth (Auth0/Clerk)
/dashboard          → User case list
/case/new           → Case intake wizard
/case/[id]          → Case detail + simulation results
/case/[id]/simulate → Live debate viewer (WebSocket)
/case/[id]/docs     → Document generator
/settings           → User profile, billing
/admin              → Admin dashboard (lawyer/clinic tiers)
```

**File Structure:**
```
frontend/
├── app/
│   ├── (auth)/
│   │   ├── login/
│   │   └── signup/
│   ├── dashboard/
│   ├── case/
│   │   ├── new/
│   │   └── [id]/
│   └── api/          # API routes (if needed)
├── components/
│   ├── ui/           # shadcn components
│   ├── case/         # Case-specific components
│   └── simulation/   # Debate viewer components
├── lib/
│   ├── api.ts        # API client
│   ├── auth.ts       # Auth helpers
│   └── utils.ts
└── hooks/
    ├── useCase.ts
    └── useSimulation.ts
```

---

### 2. Backend (FastAPI)

**Tech Stack:**
- Python 3.11
- FastAPI
- SQLAlchemy (async)
- Pydantic v2
- JWT (Auth0/Clerk integration)

**API Endpoints:**
```python
# Authentication
POST   /api/v1/auth/login
POST   /api/v1/auth/logout
GET    /api/v1/auth/me

# Cases
POST   /api/v1/cases              # Create case
GET    /api/v1/cases              # List user's cases
GET    /api/v1/cases/{id}         # Get case detail
PUT    /api/v1/cases/{id}         # Update case
DELETE /api/v1/cases/{id}         # Delete case

# Documents
POST   /api/v1/cases/{id}/documents/upload
GET    /api/v1/cases/{id}/documents
DELETE /api/v1/cases/{id}/documents/{doc_id}

# Simulations
POST   /api/v1/cases/{id}/simulate     # Start simulation
GET    /api/v1/cases/{id}/simulations  # List simulations
GET    /api/v1/simulations/{id}        # Get simulation result
WS     /api/v1/simulations/{id}/stream # Live debate stream

# Documents (Generated)
POST   /api/v1/cases/{id}/generate     # Generate document
GET    /api/v1/cases/{id}/documents/generated/{doc_id}

# Deadlines
GET    /api/v1/cases/{id}/deadlines
POST   /api/v1/cases/{id}/deadlines/calculate

# Billing
POST   /api/v1/billing/checkout       # Stripe checkout session
GET    /api/v1/billing/subscription   # Get subscription status
POST   /api/v1/billing/webhook        # Stripe webhook handler
```

**Project Structure:**
```
backend/
├── app/
│   ├── api/
│   │   ├── v1/
│   │   │   ├── endpoints/
│   │   │   │   ├── auth.py
│   │   │   │   ├── cases.py
│   │   │   │   ├── simulations.py
│   │   │   │   ├── documents.py
│   │   │   │   └── billing.py
│   │   │   └── router.py
│   │   └── deps.py          # Dependencies (auth, DB session)
│   ├── core/
│   │   ├── config.py        # Settings (pydantic-settings)
│   │   ├── security.py      # JWT, password hashing
│   │   └── exceptions.py    # Custom HTTP exceptions
│   ├── db/
│   │   ├── base.py          # SQLAlchemy base
│   │   ├── session.py       # DB session factory
│   │   └── models/          # SQLAlchemy models
│   │       ├── user.py
│   │       ├── case.py
│   │       ├── simulation.py
│   │       └── document.py
│   ├── schemas/             # Pydantic schemas
│   │   ├── user.py
│   │   ├── case.py
│   │   └── simulation.py
│   ├── services/            # Business logic
│   │   ├── auth_service.py
│   │   ├── case_service.py
│   │   ├── simulation_service.py
│   │   └── billing_service.py
│   ├── tasks/               # Celery tasks
│   │   ├── simulations.py
│   │   ├── documents.py
│   │   └── notifications.py
│   └── main.py
├── tests/
└── requirements.txt
```

---

### 3. AI Agent Orchestrator

**Debate State Machine:**
```python
from enum import Enum
from typing import List, Dict

class DebateTurn(Enum):
    PLAINTIFF_OPENING = 1
    DEFENDANT_OPENING = 2
    JUDGE_INITIAL = 3
    PLAINTIFF_REBUTTAL = 4
    DEFENDANT_REBUTTAL = 5
    JUDGE_MID = 6
    PLAINTIFF_CLOSING = 7
    DEFENDANT_CLOSING = 8
    JUDGE_FINAL = 9

class DebateStateMachine:
    def __init__(self, case_data: Dict):
        self.case_data = case_data
        self.current_turn = 0
        self.debate_history: List[Dict] = []
        self.judge_belief_state = {
            'plaintiff_win_prob': 0.5,
            'confidence': 0.0,
            'key_issues': [],
            'evidence_gaps': []
        }
    
    async def run_debate(self) -> Dict:
        """Execute 9-turn debate protocol"""
        for turn in DebateTurn:
            self.current_turn = turn.value
            
            # Get appropriate agent
            agent = self._get_agent_for_turn(turn)
            
            # Generate response
            response = await agent.generate(
                context=self._build_context(turn),
                history=self.debate_history
            )
            
            # Update debate history
            self.debate_history.append({
                'turn': turn.name,
                'agent': agent.role,
                'content': response['content'],
                'metadata': response.get('metadata', {})
            })
            
            # Update judge belief state if judge turn
            if 'JUDGE' in turn.name:
                self.judge_belief_state = response['belief_state']
        
        return self._compile_result()
```

**Agent Base Class:**
```python
class LegalAgent:
    def __init__(self, role: str, system_prompt: str):
        self.role = role
        self.system_prompt = system_prompt
        self.model = "deepseek-v3"  # via SGLang
    
    async def generate(self, context: str, history: List[Dict]) -> Dict:
        """Generate agent response"""
        prompt = self._build_prompt(context, history)
        
        response = await self._call_sglang(prompt)
        
        return {
            'content': response['text'],
            'metadata': {
                'tokens_used': response['usage'],
                'latency_ms': response['latency']
            }
        }
    
    def _build_prompt(self, context: str, history: List[Dict]) -> str:
        """Construct full prompt with system message + context + history"""
        # Implement prompt templating
        pass
    
    async def _call_sglang(self, prompt: str) -> Dict:
        """Call SGLang inference server"""
        # HTTP request to SGLang server
        pass
```

---

### 4. Citation Verification Pipeline

```python
async def verify_citations(document_text: str) -> Dict:
    """
    Extract and verify all case citations against AustLII.
    Returns verification report with hallucination score.
    """
    # Step 1: Extract citations using regex + NER
    citations = extract_citations(document_text)
    # e.g., ["Smith v Jones [2020] FCA 123", "Brown v Board (1954) 347 US 483"]
    
    verification_results = []
    
    for citation in citations:
        # Step 2: Parse citation components
        parsed = parse_citation(citation)
        # {case_name: "Smith v Jones", year: 2020, court: "FCA", number: 123}
        
        # Step 3: Search AustLII
        austlii_results = await search_austlii(parsed)
        
        if not austlii_results:
            verification_results.append({
                'citation': citation,
                'status': 'fake',
                'confidence': 1.0
            })
            continue
        
        # Step 4: Verify proposition (optional, advanced)
        # Extract proposition from document context
        proposition = extract_proposition(document_text, citation)
        
        # Compare with AustLII case headnote using embeddings
        if proposition:
            similarity = await compute_similarity(
                proposition,
                austlii_results[0]['headnote']
            )
            
            status = 'verified' if similarity > 0.7 else 'unverified'
        else:
            status = 'verified'  # Citation exists, can't verify proposition
        
        verification_results.append({
            'citation': citation,
            'status': status,
            'austlii_url': austlii_results[0]['url'],
            'similarity_score': similarity if proposition else None
        })
    
    # Step 5: Calculate hallucination score
    fake_count = sum(1 for r in verification_results if r['status'] == 'fake')
    hallucination_score = fake_count / len(verification_results) if verification_results else 0.0
    
    return {
        'citations': verification_results,
        'hallucination_score': hallucination_score,
        'safe_to_file': hallucination_score < 0.05  # <5% fake citations
    }
```

---

### 5. Database Models (SQLAlchemy)

```python
from sqlalchemy import Column, String, Text, ForeignKey, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMPTZ
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    email = Column(String, unique=True, nullable=False)
    role = Column(String, CheckConstraint("role IN ('individual', 'lawyer', 'clinic')"))
    subscription_tier = Column(String)
    created_at = Column(TIMESTAMPTZ, default=func.now())
    
    cases = relationship('Case', back_populates='user', cascade='all, delete-orphan')

class Case(Base):
    __tablename__ = 'cases'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    title = Column(String, nullable=False)
    jurisdiction = Column(String, nullable=False)
    cause_of_action = Column(String, nullable=False)
    status = Column(String, default='intake')
    created_at = Column(TIMESTAMPTZ, default=func.now())
    updated_at = Column(TIMESTAMPTZ, default=func.now(), onupdate=func.now())
    
    user = relationship('User', back_populates='cases')
    documents = relationship('Document', back_populates='case', cascade='all, delete-orphan')
    simulations = relationship('Simulation', back_populates='case', cascade='all, delete-orphan')

class Simulation(Base):
    __tablename__ = 'simulations'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey('cases.id'), nullable=False)
    debate_transcript = Column(JSONB, nullable=False)
    outcome_prediction = Column(JSONB, nullable=False)
    weakness_report = Column(JSONB)
    hallucination_score = Column(Float)
    created_at = Column(TIMESTAMPTZ, default=func.now())
    
    case = relationship('Case', back_populates='simulations')

class Document(Base):
    __tablename__ = 'documents'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey('cases.id'), nullable=False)
    file_path = Column(String, nullable=False)
    file_type = Column(String, nullable=False)
    uploaded_at = Column(TIMESTAMPTZ, default=func.now())
    
    case = relationship('Case', back_populates='documents')
```

---

### 6. Deployment Configuration

**Docker Compose (Local Development):**
```yaml
version: '3.8'

services:
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_USER: lexsim
      POSTGRES_PASSWORD: devpassword
      POSTGRES_DB: lexsim
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  backend:
    build: ./backend
    command: uvicorn app.main:app --host 0.0.0.0 --reload
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: postgresql://lexsim:devpassword@postgres/lexsim
      REDIS_URL: redis://redis:6379
      AUTH0_DOMAIN: ${AUTH0_DOMAIN}
      SGLANG_URL: http://sglang:3000
    depends_on:
      - postgres
      - redis

  celery:
    build: ./backend
    command: celery -A app.tasks worker --loglevel=info
    environment:
      DATABASE_URL: postgresql://lexsim:devpassword@postgres/lexsim
      REDIS_URL: redis://redis:6379
    depends_on:
      - postgres
      - redis

  frontend:
    build: ./frontend
    ports:
      - "3000:3000"
    environment:
      NEXT_PUBLIC_API_URL: http://localhost:8000
    depends_on:
      - backend

  sglang:
    image: lmsysorg/sglang:latest
    command: python -m sglang.launch_server --model deepseek-ai/DeepSeek-V3 --port 3000
    volumes:
      - model_cache:/root/.cache
    ports:
      - "3000:3000"
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

volumes:
  postgres_data:
  model_cache:
```

**Production (AWS):**
```yaml
# Infrastructure as Code (Terraform/Pulumi)
- EKS cluster (Kubernetes)
- RDS PostgreSQL (Multi-AZ, ap-southeast-2)
- ElastiCache Redis
- S3 buckets (documents, logs)
- CloudFront (CDN for frontend)
- Application Load Balancer
- EC2/G5 instances for SGLang (GPU)
- Auth0 for authentication
- Stripe for payments
```

---

## Security Checklist

- [ ] **Encryption:** TLS 1.3 everywhere, AES-256 at rest
- [ ] **Authentication:** Auth0/Clerk with MFA for lawyer accounts
- [ ] **Authorization:** Row-level security in PostgreSQL
- [ ] **Rate Limiting:** 100 req/min per user (Redis-backed)
- [ ] **Audit Logging:** All AI inputs/outputs logged (7 years retention)
- [ ] **Data Residency:** All data in AWS ap-southeast-2 (Sydney)
- [ ] **Backup:** Daily automated backups, point-in-time recovery
- [ ] **Monitoring:** Prometheus + Grafana, Sentry for error tracking
- [ ] **Compliance:** APP 1-13 compliant, LPP warnings in UI

---

## Performance Targets

| Metric | Target |
|--------|--------|
| **API Latency (p95)** | <200ms (non-AI endpoints) |
| **Simulation Time** | <5 minutes (7-turn debate) |
| **Document Generation** | <30 seconds |
| **Citation Verification** | <10 seconds per citation |
| **Uptime SLA** | 99.9% (lawyer/clinic tiers) |
| **Concurrent Users** | 1,000 active sessions |

---

## Monitoring & Observability

**Metrics to Track:**
- Simulation success rate
- Hallucination score distribution
- Citation verification failure rate
- User conversion funnel (intake → simulation → payment)
- API error rates (per endpoint)
- GPU utilization (SGLang server)

**Alerting Rules:**
- Hallucination score >10% for any generated document → Slack alert
- Simulation failure rate >5% → PagerDuty
- API latency p95 >500ms for 5 minutes → Slack alert
- Database connection pool exhaustion → PagerDuty

---

## Disaster Recovery

**RTO (Recovery Time Objective):** 4 hours  
**RPO (Recovery Point Objective):** 1 hour

**Backup Strategy:**
- PostgreSQL: Continuous WAL archiving + daily snapshots
- S3: Versioning enabled, cross-region replication to Melbourne
- Auth0: Export user data weekly
- Code: GitHub Actions CI/CD with rollback capability
