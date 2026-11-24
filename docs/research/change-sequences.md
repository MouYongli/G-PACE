# Controlled Change Sequences: Generator Design

Design of the controlled change-sequence generator (task T008), the primary evidence for RQ2 and the source of the RQ3 maintenance surface (plan sections 4.2, 6.4 and 8.3). The design is fixed before any staleness result is seen. T015 implements it, T016 audits the generated sequences, and the benchmark slug is `change-seq` (`docs/research/benchmarks.md`).

Notation follows plan section 3: version $t$ is the state after message $h_t$ is written, $\kappa$ is a knowledge version, $\tau$ a valid time, and the four entry kinds are claims, attributions, evidence links and supersession events. Numbers marked **[assumption]** are planning inputs, not measurements; they are re-checked where stated. Nothing in this document cites a result that is not already in the plan or in `docs/research/literature.md`.

## 1. Scope and terminology

The plan uses "template family" in two senses. This document keeps them apart:

| Term here | Meaning | Plan usage |
| --- | --- | --- |
| **View template** | One of the six resident-view templates of plan section 5.4 (list, current state, count, requested constraints, pending candidates, current choice) | "Template family" in section 5.4 and in D013's recommendation "one small function per template family" |
| **Binding** | A view template with its parameters bound, for example List(Melanie, playsInstrument). Every binding the world of a sequence admits has gold labels, whether or not a system instantiates it as a resident view | "Template view" in section 6.4 |
| **Scenario family** | A domain micro-world used by the generator: entity types, predicates, a task type, value lexicons and dialogue skeletons. The unit of the development / held-out split, of the audit sample and of clustering | "Template family" in section 6.4 (validity) and 6.9 (clustering) |
| **Macro** | One planned change: a small composition of primitive events with an intended change type and a focus binding (section 3.3) | — |
| **Change type** | One of the seven types C1–C7 of plan section 6.4. It is a property of a pair (message, binding), not of a message alone (section 4) | "Change type" |

The gold-staleness procedure is defined per view template, because a view's semantics depends only on its template; scenario families supply bindings and lexicons, not semantics.

## 2. World model

A sequence is a two-party dialogue between `user` and `assistant` (the "system" of the plan's MultiWOZ examples), grouped into dated **episodes** (the generator-defined segment of plan section 6.2). Every message carries an ID, a version $t$, an episode, a speaker and a world timestamp (the episode date). The adapter maps the speaker `assistant` to the contract role `agent` and `user` to `user` (`docs/research/contracts.md`, benchmark mapping of `change-seq`).

Each scenario family declares:

- **Entities.** The user, further named entities of the family's entity types (names unique within a sequence), and catalogue items (for example trains). No aliases or entity merges in the main configuration (section 3.6).
- **State predicates** with an exclusivity flag: at least one multi-valued predicate (for example `playsInstrument`) and at least one exclusive predicate (for example `livesIn`). Each has an authority speaker whose own statements set state: `user` for facts about the user, `assistant` for catalogue facts (for example `scheduledArrival`).
- **A task type** with constraint predicates (exclusive per task, for example `arriveBy`, `destination`), a choice predicate `selectedService`, and catalogue predicates of the chosen item (for example `scheduledArrival`, written `arr` below).
- **Value lexicons** for every predicate, and dialogue skeletons for the renderer (section 7).

Requiring every family to contain all three parts makes all six view templates and all seven change types realisable in every family, so change type is not confounded with scenario family.

**Valid time.** A claim has a valid interval $\tau(c)=[\tau_s(c),\tau_e(c))$. A present-tense statement without a date has start $\bot$ (unknown, at most the message date) and no end; no absolute date is invented (plan section 5.2). A change or a correction may state a start date ("I moved on 1 November"). A past-dated statement ("I lived in Hamburg from 2015 to 2019") has both ends; it describes past state and never competes for the current state. Scope $\omega$ is fixed per predicate in the main configuration.

## 3. Event grammar

### 3.1 Primitive events

The event log $\Lambda=\langle\lambda_1,\dots,\lambda_N\rangle$ has one record per message, $\lambda_t=(t,u_t,\theta_t,E_t)$: version, speaker, world timestamp and a possibly empty list of primitive events. There are three primitive events. Each maps deterministically to the four entry kinds of plan section 3.2, all stamped $t$:

| Primitive | Fields | Gold-graph entries at version $t$ |
| --- | --- | --- |
| `NewClaim(c, s, p, o, τ)` | New claim ID and proposition; $\omega$ from the predicate | Claim $c$; evidence link $(c, h_t)$ |
| `Stance(c, f, ρ, π, derived)` | Stance of the message speaker $u_t$ on claim $c$: communicative function $f$ (request, offer, accept, reject, confirm, inform, commit, question), report mode $\rho$ (own, quote, hypothetical), polarity $\pi$, and whether it is an assistant restatement (`derived`, plan section 5.2) | Attribution $a=(u_t,c,f,\rho,\pi,\gamma{=}\text{certain},t)$; evidence link $(c, h_t)$ if not already added at $t$ |
| `Supersede(c, η)` | Claim $c$ is no longer currently accepted; kind $\eta\in\{\text{change},\text{correction}\}$ | Supersession event $(c, t, \eta)$ |

Every `NewClaim` is followed in the same message by a `Stance` on it (a claim always has an attributed source). Mentioning an existing proposition never creates a new claim: it is a `Stance` on the existing one (plan section 3.2). Evidence links are at message granularity; span anchors are optional and come from the renderer's value positions (section 7).

### 3.2 Well-formedness constraints

The generator emits only event logs that satisfy these constraints; T015 checks each one as a unit test.

- **G1 (append-only, unique propositions).** A `NewClaim` never repeats the $(s,p,o,\omega,\tau)$ of an existing claim.
- **G2 (attribution guard).** `Supersede(c, η)` appears only together with an own-statement stance $a'$ of the message speaker that either (i) introduces a replacing claim $c'$ with the same subject, predicate and scope as $c$, on an exclusive predicate, or (ii) is a negative-polarity stance on $c$ itself (removal); and some attribution on $c$ has the same speaker and function as $a'$. Case (i) is the guard of plan section 3.2. Case (ii), for example "I no longer play the violin", extends the guard to supersession without a replacing claim. Two macros rely on it: `m-remove` and the multi-valued variant of `m-correct`. T014 must confirm it; otherwise both are disabled (open question 6).
- **G3 (no double supersession).** A claim is superseded at most once. This keeps the exactness conditions of plan section 3.4 checkable.
- **G4 (introduction).** A state claim is introduced by an own, positive `inform` of its authority speaker, or by a non-endorsing stance (request, offer, question, quote, hypothetical) that a later message may endorse. `confirm` occurs only on claims that already exist.
- **G5 (offers carry catalogue facts).** An offer of item $o$ introduces, in the same message, the catalogue claims of $o$ used by the current-choice view (for example `(o, scheduledArrival, ·)` informed by the assistant). The inner join of that view then always has a partner for offered items.
- **G6 (no re-acceptance).** A candidate that the user rejected is not accepted again.
- **G7 (no state in fillers).** Filler messages have $E_t=\emptyset$ and must not express any proposition about a predicate of the family (audited, section 8).
- **G8 (no fallback of the choice).** The user rejects the current choice only when no earlier accepted and unrejected candidate of the task exists, so the current-choice view never falls back to an earlier choice.

### 3.3 Change macros

Macros are the productions of the grammar. Each has an intended change type, a focus binding and preconditions; `x` is an entity, `p` a predicate, `k` a task.

```text
sequence     ::= setup-episode episode+
setup-episode::= message+                          -- the first L_0 messages; introduces the world; no reads (section 5)
episode      ::= message+
message      ::= speaker timestamp event*
macro        ::= m-change | m-remove | m-add | m-first | m-offer | m-constraint
               | m-accept | m-reject | m-past | m-correct | m-mention | m-blocked

m-change     ::= NewClaim(c',x,p,o',τ') Stance(c',inform,own,+) Supersede(c,change)     -- p exclusive, c current; C1
m-remove     ::= Stance(c,inform,own,−) Supersede(c,change)                            -- p multi-valued; C1
m-add        ::= NewClaim(c',x,p,o',τ) Stance(c',inform,own,+)                          -- p multi-valued, o' new; C2 (C4 for the count)
m-first      ::= NewClaim(c',x,p,o',τ) Stance(c',inform,own,+)                          -- p exclusive, no current claim; C2
m-offer      ::= NewClaim(c',k,selectedService,o') Stance(c',offer,own,+) G5-catalogue  -- assistant; C2 for pending
m-constraint ::= NewClaim(c',k,q,v) Stance(c',request,own,+) [Supersede(c,change)]      -- user; C2, or C1 when revising
m-accept     ::= Stance(c,accept,own,+)                                                -- user, c offered; C3 for pending, C2 or C4 for choice
m-reject     ::= Stance(c,reject,own,+)                                                -- user, c offered; C3
m-correct    ::= NewClaim(c',x,p,o'',τ'') Stance(c',inform,own,+) Supersede(c,correction) -- p exclusive, c from an earlier episode; C5
               | Stance(c,inform,own,−) Supersede(c,correction) [NewClaim(c',x,p,o'') Stance(c',inform,own,+)]
                                                                                       -- p multi-valued ("I said violin, I meant viola"); C5; needs G2(ii)
m-mention    ::= Stance(c,inform|confirm,own,+) | Stance(c,inform,own,+,derived)        -- c existing; C6
m-past       ::= NewClaim(c',x,p,o',[τ_s,τ_e)) Stance(c',inform,own,+)                  -- p exclusive, closed past interval; C7a (local filter)
m-blocked    ::= NewClaim(c',...) Stance(c',f,ρ,π)  with f ∈ {request, offer, question} on a state predicate,
                 or ρ ∈ {quote, hypothetical}                                          -- C7a (guard-blocked)
```

Further C7 instances arise from macros on other bindings that share a predicate with the target (section 4). A `m-correct` that changes only the date ($o''=o(c)$, $\tau''\neq\tau(c)$) is the date-correction sub-kind. Arrival changes of a chosen item (`m-change` on a catalogue predicate by the assistant) are C1 for the current-choice view. An acceptance is C2 for the current-choice view when no choice exists yet and C4 (order) when it switches the choice.

**Unconfirmed alternatives.** Every task receives $K\in\{1,2,3\}$ offers (uniform **[assumption]**); with probability $0.3$ **[assumption]** none is ever accepted, and otherwise at most one accepted offer is the latest. Offers that are never accepted stay in the pending view and must never appear as the current choice.

### 3.4 Presupposition questions

For a binding whose answer changed by C1 or C5 before read version $r$, the generator may emit a question whose wording presupposes the earlier value (for example "How long is the trip from Munich, where I live?" after the move to Cologne). The gold record holds the current answer, `premise_outdated = true` and the outdated value. Correct means the answer uses the current value or rejects the premise; adopting the outdated value is stale-value use (plan section 6.7).

### 3.5 Paired known-then and seen-from-now questions

For an exclusive binding $(x,p)$, a world time $\tau$ and a knowledge version $k<r$, the pair is:

- **known then:** "When you booked my train, where did you have me living?", gold $\mathrm{Hist}(x,p,\tau,k)$;
- **seen from now:** "Given what you know now, where was I actually living when you booked my train?", gold $\mathrm{Hist}(x,p,\tau,r)$;

with $\mathrm{Hist}$ defined in section 6.2. The knowledge version $k$ is referred to by an anchor, a distinct earlier event with a unique description (a booking, an offer); the audit checks that the anchor identifies $k$. Pairs are generated in two kinds in equal numbers: **differing** pairs, where a correction or a past-dated statement between $k$ and $r$ changes the state at $\tau$, and **control** pairs, where both answers agree. Historical questions are restricted to exclusive predicates in the main configuration, because the supersession entry of plan section 3.2 carries no valid end, so the past membership of a multi-valued predicate is not determined by the graph (open question 2).

### 3.6 Out of scope for the main configuration

Vocabulary changes, entity aliases and merges, multi-party dialogue, negative-polarity statements other than removals, and claims about read-time-relative windows. The first two fall outside the assumptions of the proposition in plan section 3.4. An optional `alias-mentions` switch may be added later as a robustness probe; it is off in every preregistered cell.

## 4. Change types

### 4.1 Deterministic classification

The type of message $t$ with respect to binding $b$ of view template $V$ is computed by a decision list over the event log. Definitions, all at version $t-1$ unless stated:

- $W_b$: the claims in any witness of $b$ (section 6.2).
- $R_b$: the **relevant** claims of $b$, those whose subject and predicate match a claim pattern of $V$ with $b$'s constants, ignoring attribution constraints and filters. The patterns are listed per view template in section 6.2 and declared statically in the view-template spec, not derived from a compiled query.
- $P_b$: the predicates of $V$'s patterns.

First match wins:

| Step | Type | Condition on $E_t$ |
| --- | --- | --- |
| 1 | C5 late correction | `Supersede(c, correction)` with $c\in R_b$ |
| 2 | C1 state change superseding a cited claim | `Supersede(c, change)` with $c\in W_b$ |
| 3 | C3 negation hit | `Stance(c, f)` with $c\in R_b$ and $f$ the function of a negated pattern of $V$ (pending: accept, reject; current choice: reject) |
| 4 | C4 count or order | Some $c\in R_b$ **newly matches** a positive pattern of $V$ at $t$, and $V$ is the count, or $V$ selects a latest state and its candidate set at $t-1$ was non-empty |
| 5 | C2 new match (sub-kind "empty to non-empty" when $\mathrm{ans}_{t-1}(b)=\emptyset$) | Some $c\in R_b$ newly matches a positive pattern of $V$ at $t$ |
| 6 | C6 repeated mention | A `Stance` on $c\in W_b$ |
| 7 | C7 irrelevant update | Some entry of $E_t$ has a predicate in $P_b$. Sub-kinds (a set, since several can apply): (a) a claim in $R_b$ that fails the attribution constraint, report mode, polarity or a local filter of its pattern; (b) the same predicate under another binding; (c) a join pattern matched without a partner |
| — | untouched | Otherwise, including $E_t=\emptyset$ |

A claim **newly matches** a positive pattern at $t$ if it satisfies the pattern with its attribution constraint and local filters at $t$, did not at $t-1$, and, for a pattern inside a join, has a join partner at $t$. All three conditions are evaluated on the derived state of section 6.1, not by comparing answers.

The definitions use only entry kinds and fields, so the same decision list classifies change sets of extracted graphs in the natural-distribution measurement (plan section 6.5), where $W_b$ and $R_b$ come from re-query instead of the reference functions.

### 4.2 Change type and outcome

The **outcome** of $(t,b)$ is answer-stale, citation-stale or neither, computed independently from the fingerprints of section 6.3. Type and outcome are reported as a cross-table, because some types are designed to produce no change (over-marking probes):

| Type | Possible outcomes | Designed over-marking cases |
| --- | --- | --- |
| C1 | answer | — |
| C2 | answer | — |
| C3 | answer or neither | Rejecting an already accepted candidate leaves the pending view unchanged; rejecting an accepted candidate that is no longer the latest choice leaves the current-choice view unchanged (patterns inside negation over-approximate, plan section 3.4) |
| C4 | answer | — |
| C5 | answer, or citation (date-only correction) | — |
| C6 | citation | — |
| C7 | neither | (a) caught by predicate level, and by claim patterns that ignore attribution constraints or local filters (the `m-past` probe separates the "claim pattern" and "claim pattern with local filters" rungs of plan section 3.4); (b) caught by predicate level only; (c) caught by claim-pattern push without confirmation |
| untouched | neither | Caught only by "rebuild every turn" |

T015 asserts these invariants on every generated sequence, together with the converse: every staleness has a type in C1–C6. A violation is a generator or reference-function bug.

## 5. Read schedule

A **read point** is a version $r$ after the setup episode ($r > L_0$, $L_0=\max(10, 0.1L)$). Every version is readable, because labels and fingerprints exist for every version (section 6). At a read point:

- the replay probe checks every binding's resident view (ablation A needs no questions; D013, `runner/probes/`);
- the harness asks $q=3$ questions **[assumption]**, each a read task at version $r$ targeting one binding: one binding whose answer changed since the previous read point if any, one binding drawn uniformly, and one special slot rotating over a presupposition question, a known-then / seen-from-now pair (both members asked at $r$, adding a fourth question), and an abstention question (a binding whose gold answer is empty, for example the current choice before any acceptance).

Three schedule types, each fully determined by the sequence seed:

| Schedule | Read points | Use |
| --- | --- | --- |
| Uniform `U(M)` | $M$ points evenly spaced over $(L_0, L]$ | Maintenance surface; cost |
| Anchored `A(M, d)` | Half of the points uniform, half placed $d\in\{1,5\}$ messages after randomly chosen focus macros | Ablation A: raises the share of stale instances and of single-type intervals |
| Poisson `P(I)` | Gaps drawn from a geometric distribution with mean $I$ | Sensitivity check of the uniform results |

Reads never write to the history (plan section 6.8), so several schedules can be overlaid on the same messages. The schedule is invisible to systems: a read task is delivered only at its version.

An instance of ablation A is a pair (read point $r_j$, binding $b$). Its **interval** is $(r_{j-1}, r_j]$. Instances whose interval contains changes of more than one type with respect to $b$ form a separate "mixed" stratum; the anchored schedule with $d=1$ exists to produce single-type intervals.

**Question-level change-type label.** Every question record in a schedule carries two fields, computed from `labels.jsonl` for its target binding $b$ over the interval $(r_{j-1}, r_j]$ of its read point in that schedule (for the first read point, $(L_0, r_1]$):

- `change_types`: the set of change types C1–C7 of $b$ at the messages of the interval (untouched messages contribute nothing);
- `change_type`: the single member if the set has one element, `none` if it is empty, and `mixed` otherwise.

Paired questions also carry `pair_id` and `pair_role` (`known-then` or `seen-from-now`). The adapter copies these fields, with the question type, into the `labels` object of the read-task record (`docs/research/contracts.md`). The label depends on the schedule, because the interval does; overlaid schedules therefore have their own question records.

## 6. Gold staleness from the event log

This section gives the deterministic procedure required by the T008 acceptance. It defines the semantics of the six view templates directly on the event log; the reference functions implement these definitions and nothing else.

### 6.1 Derived state at a knowledge version

From the prefix $\Lambda_{\le\kappa}$:

- $C_\kappa$: claims introduced at versions $\le\kappa$, with fields $s,p,o,\tau$ and introduction version $\kappa(c)$.
- $A_\kappa(c)$: attributions on $c$ at versions $\le\kappa$, each with speaker, function, report mode, polarity, `derived` and version $t(a)$.
- $\mathrm{Ev}_\kappa(c)$: message IDs with an evidence link to $c$ at versions $\le\kappa$.
- $\mathrm{Cur}_\kappa(c)$: no supersession event on $c$ at a version $\le\kappa$ ("currently accepted").
- $\mathrm{NC}_\kappa(c)$: no supersession event of kind correction on $c$ at a version $\le\kappa$.
- $\mathrm{End}_\kappa(c)$, the endorsing attributions: $a\in A_\kappa(c)$ with speaker = the authority speaker of $p(c)$, function inform, report mode own, polarity positive, not derived. $c$ is **endorsed** if $\mathrm{End}_\kappa(c)\neq\emptyset$.
- $\mathrm{Att}_\kappa(c,u,f)$: attributions on $c$ with speaker $u$, function $f$, report mode own and positive polarity.

### 6.2 Semantics of the view templates

$\mathrm{ans}$ is a set, $\mathrm{wit}$ maps each answer to its set of minimal witnesses (each a set of entry IDs), and $\mathrm{ev}$ is the union of $\mathrm{Ev}_\kappa$ over the claims in all witnesses, following plan section 3.4. The pattern column lists the claim patterns in the notation of plan section 3.3; the attribution constraint also fixes report mode own and positive polarity, which the IR must express as a local filter on the attribution (to be confirmed by T017).

| Template | Binding | Claim patterns | Definition at $\kappa$ |
| --- | --- | --- | --- |
| V1 List | $(x,p)$, $p$ multi-valued | $(x,p,?o)[\text{auth},\text{inform}]$; currently accepted | $K=\{c: s{=}x, p{=}p, \mathrm{Cur}_\kappa(c), c \text{ endorsed}\}$; $\mathrm{ans}=\{o(c):c\in K\}$; witnesses of $o$: $\{\{c,a\}: o(c){=}o, a\in\mathrm{End}_\kappa(c)\}$ |
| V2 Current | $(x,p)$, $p$ exclusive | As V1, with the local filter "no valid end", plus latest-state selection by version | $K=\{c\in K_{V1}: \tau_e(c) \text{ unset}\}$; $c^*=\arg\max_{K}\kappa(c)$; $\mathrm{ans}=\{o(c^*)\}$ or $\emptyset$; witnesses those of $c^*$ |
| V3 Count | $(x,p)$, $p$ multi-valued | As V1, with distinct count | $\mathrm{ans}=\{\lvert\mathrm{ans}_{V1}\rvert\}$; witnesses: the union of the members' witnesses (one witness set per member, plan section 3.4) |
| V4 Requested constraints | task $k$ | $(k,?q,?v)[\text{user},\text{request}]$, $?q\in\mathrm{Cons}(k)$; currently accepted | $\mathrm{ans}=\{(q,v): c=(k,q,v), \mathrm{Cur}_\kappa(c), \mathrm{Att}_\kappa(c,\text{user},\text{request})\neq\emptyset\}$; witnesses $\{c,a\}$ per request attribution $a$ |
| V5 Pending | task $k$ | $(k,\text{sel},?o)[\text{assistant},\text{offer}]$; NOT EXISTS $(\cdot)[\text{user},\text{accept}]$ and NOT EXISTS $(\cdot)[\text{user},\text{reject}]$ on the same claim; currently accepted | $\mathrm{ans}=\{o(c): s{=}k, p{=}\text{sel}, \mathrm{Cur}_\kappa(c), \mathrm{Att}(c,\text{assistant},\text{offer})\neq\emptyset, \mathrm{Att}(c,\text{user},\text{accept})=\mathrm{Att}(c,\text{user},\text{reject})=\emptyset\}$; witnesses $\{c,a_{\text{offer}}\}$ |
| V6 Current choice | task $k$ | $(k,\text{sel},?o)[\text{user},\text{accept}]$; NOT EXISTS $(\cdot)[\text{user},\text{reject}]$; join $(?o,\text{arr},?t)[\text{assistant},\text{inform}]$; currently accepted on both; latest-state selection by acceptance version | $A=\{(c,a): s{=}k, p{=}\text{sel}, \mathrm{Cur}_\kappa(c), a\in\mathrm{Att}(c,\text{user},\text{accept}), \mathrm{Att}(c,\text{user},\text{reject})=\emptyset\}$; $c^*$ from $\arg\max_A t(a)$; $\mathrm{ans}=\{(o(c^*),o(d)): d \text{ current}, s(d){=}o(c^*), p(d){=}\text{arr}, \mathrm{Att}(d,\text{assistant},\text{inform})\neq\emptyset\}$; witnesses $\{c^*,a,d,a_d\}$ |

Notes:

- V4 is the set of constraints the user has asked for and not revised. An offer never enters it; a user's own revision does (by `m-constraint` with supersession). The plan calls this view "original constraints"; whether a user revision should replace the original value is open question 1.
- In V2, supersession normally leaves $\lvert K\rvert\le1$; the selection only makes the definition total. The "no valid end" filter keeps past-dated claims (`m-past`) out of the current state without comparing with the time of reading, which plan section 3.3 forbids. Selection by acceptance version in V6 makes a switch of choice a C4 order change.
- Ties in an $\arg\max$ are broken by claim ID; the generator avoids ties in any case.

**Historical state** (paired questions, exclusive predicates only). With $\bot$ read as $-\infty$:

$$
\mathrm{Hist}(x,p,\tau,\kappa)=o(c^*),\quad c^*=\arg\max_{(\tau_s,\,\kappa(c))}\{c\in C_\kappa: s{=}x, p{=}p, c\text{ endorsed}, \mathrm{NC}_\kappa(c), \tau_s(c)\le\tau, \tau_e(c) \text{ unset or } \tau<\tau_e(c)\}
$$

following plan section 3.3: historical queries exclude only corrected claims, and a claim superseded by a change stays visible as past state; an open claim holds until a later-starting claim takes over. The maximum is lexicographic: by start, then by introduction version (the latest introduced wins), then by claim ID.

Undated starts make the definition depend on a date the dialogue never states, so the generator applies three rules before emitting a historical question:

1. **Two readings.** $\mathrm{Hist}$ is evaluated twice, once with every undated start at $-\infty$ and once at the date of the message that introduced the claim. The question is emitted only when both readings give the same answer.
2. **No competing undated claims.** The question is skipped when, under the $-\infty$ reading, more than one undated candidate with different objects qualifies. Under that reading all undated starts are equal, and the tie-break by introduction version would pick the latest stated value even for a $\tau$ before it was stated (for example an undated "I live in Munich" superseded by an undated "I live in Cologne now").
3. **Mixed dated and undated candidates.** Under the $-\infty$ reading every dated candidate that qualifies beats every undated one; under the message-date reading they compare by date. Rule 1 emits the question only where both orders agree, which happens when the dated start lies after the undated claim's message date (as in section 6.5) or the dated candidate does not qualify at $\tau$.

So the gold never depends on an invented date.

### 6.3 Procedure

```text
GoldStaleness(Λ, family spec, bindings B):
    S ← empty derived state
    for t = 0 .. N:
        if t > 0: S ← S + entries(E_t)                 # section 3.1 mapping, stamps t
        for b in B:
            (ans, wit, ev) ← F[template(b)](S, b, κ = t)  # section 6.2, pure function
            store canonical (ans, wit, ev) and fingerprints
              fa[b][t] = H(ans), fw[b][t] = H(wit), fe[b][t] = H(ev)
    per message t ≥ 1 and binding b:
        answer_stale[b][t]   = ans_t(b) ≠ ans_{t−1}(b)
        citation_stale[b][t] = not answer_stale[b][t] and (wit, ev)_t(b) ≠ (wit, ev)_{t−1}(b)
        type[b][t]           = decision list of section 4.1
    for any pair r0 ≤ r (a view with cut-off r0 read at r):
        answer-stale   iff ans_{r0}(b) ≠ ans_r(b)
        citation-stale iff ans equal and (wit, ev)_{r0}(b) ≠ (wit, ev)_r(b)
```

$H$ is SHA-256 over a canonical JSON serialisation (sets sorted, IDs as strings). Equality is decided on the canonical values; the hashes are stored for compactness. Canonical values are stored only at versions where they change.

**Determinism.** The procedure is a pure function of the event log, the family spec and the binding list. It uses no randomness, no model call, no SPARQL engine and no wall-clock time. Its cost is $O(N\cdot|B|)$ evaluations of small set expressions.

**Spans, not only adjacent messages.** Staleness between $r_0$ and $r$ is not the disjunction of the per-message labels in between: a new match followed by a correction that removes it leaves the answer unchanged. Storing $(\mathrm{ans},\mathrm{wit},\mathrm{ev})$ per version makes every pair derivable. This is needed because a strategy that missed staleness keeps an old cut-off $r_0$, and its later decisions are scored against that $r_0$.

### 6.4 Independence from the query compiler

**Decision: the gold staleness is independent of the query compiler of the system under test.** This follows the recommendation of D013.

- The reference functions are one small function per view template (six in total), written against the derived state of section 6.1. They live in `src/grace/eval/datasets/changeseq/invalidation.py` and import nothing from `src/grace/context/pipeline/query/`, no IR, and no SPARQL engine. From `src/grace/context/` the generator imports only `memory/graph/`, and only for the entry types of the gold graph (T015 acceptance; D013 import rule, enforced in `tests/contracts/`).
- The alternative, running compiled queries on the gold graph, would make the end-to-end reference share the compiler with the system. A compiler error (a dropped negated pattern, a wrong attribution constraint) would then shift the reference and the system together and be invisible in the end-to-end miss rate.
- **Cross-check.** On every gold graph, read-time re-query with the compiled IR template must reproduce $(\mathrm{ans},\mathrm{wit},\mathrm{ev})$ of the reference function at every version and binding. Any disagreement is a bug in the compiler, the IR template or the reference function, and is resolved before any staleness result is reported (T015 acceptance). With independent truth this check also tests the compiler.
- **Remaining common-mode risks.** Both implementations follow the semantics of section 6.2. A misreading of that table shared by both would not be caught by the cross-check. Mitigations: the table is the single written source; hand-computed fixtures (section 6.5 and the three running examples of plan section 3.5) are unit tests of both implementations; and a reviewer other than the implementer of T017 reviews the reference functions. The entry types shared through `memory/graph/` are data classes only and carry no query logic.

### 6.5 Worked example

A fictional prefix with six bindings: V2(user, livesIn), V1 and V3(user, playsInstrument), and V4, V5, V6 for train task $k_1$. Labels are $(t-1,t)$; "ans" means answer-stale, "cit" citation-stale, "–" untouched.

| $t$ | Speaker | Message | Events | V2 | V1 | V3 | V4 | V5 | V6 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | user | I live in Munich. | `NewClaim(c1, user, livesIn, Munich, ⊥)`, inform | C2 ans | – | – | – | – | – |
| 2 | user | Book me a train to Berlin on Saturday, arriving by 18:00. | `NewClaim(c2, k1, arriveBy, 18:00)`, `NewClaim(c3, k1, destination, Berlin)`, both request | – | – | – | C2 ans | – | – |
| 3 | assistant | ICE 947 leaves at 12:10 and arrives at 17:25. Shall I book it? | `NewClaim(c4, k1, sel, ICE947)` offer; `NewClaim(c5, ICE947, arr, 17:25)` inform | – | – | – | – | C2 ans | C7a, C7c, neither |
| 4 | user | Yes, that one. | `Stance(c4, accept)` | – | – | – | – | C3 ans | C2 ans |
| 5 | user | I play the violin, by the way. | `NewClaim(c6, user, playsInstrument, violin)`, inform | – | C2 ans | C4 ans | – | – | – |
| 6 | assistant | Noted, and you're based in Munich. | `Stance(c1, inform, derived)` | C6 cit | – | – | – | – | – |
| 7 | user | I moved to Cologne on 1 November. | `NewClaim(c7, user, livesIn, Cologne, 1 Nov)`, inform; `Supersede(c1, change)` | C1 ans | – | – | – | – | – |
| 8 | user | Sorry, I got that wrong: I moved on 20 October. | `NewClaim(c8, user, livesIn, Cologne, 20 Oct)`, inform; `Supersede(c7, correction)` | C5 cit | – | – | – | – | – |

At $t=3$ the offer is relevant to V6 but carries no acceptance (C7a), and the arrival claim matches V6's join pattern without a partner (C7c); a claim-pattern strategy without confirmation marks V6, read-time re-query does not. At $t=4$ one acceptance, which supersedes nothing, empties V5 through its negated pattern and fills V6 through its attribution-constrained positive pattern (plan section 3.5). At $t=6$ the assistant's restatement adds an evidence link but no endorsing attribution: V2 is citation-stale only. At $t=8$ the answer stays Cologne while the witness moves from $c7$ to $c8$. **Dates of the fixture.** Message 1 is dated before 20 October (for example 15 October), messages 2–6 on 24 October, and messages 7 and 8 after 1 November (for example 3 November), so that both past-tense statements ("moved on 1 November", "on 20 October") refer to dates before they are made. The anchor "when you booked my train" refers to $k=4$, and its world time is the booking date $\tau=$ 24 October. Then $\mathrm{Hist}(\text{user},\text{livesIn},24\text{ Oct},4)=$ Munich (only $c1$ is known) and $\mathrm{Hist}(\cdot,24\text{ Oct},8)=$ Cologne ($c7$ is corrected away and $c8$ starts on 20 October), under both readings of $c1$'s undated start ($-\infty$ and 15 October): a differing known-then / seen-from-now pair. This table, with these dates, is a required unit-test fixture of T015.

## 7. Surface rendering

**Renderer.** Surface text is written by a model that no evaluated system uses (plan section 6.4): not the primary model, the contemporary small model, the long-context answering model, the larger writer, nor any model of their families. It should also differ from the blind judge, so that the judge does not favour the renderer's phrasing. The model is chosen in phase 1 together with the other model choices (plan section 7.1) and recorded in the dataset manifest with its exact snapshot; open-weight models served through `envs/serve` are preferred for reproducibility (open question 3).

**Input per message.** Speaker, episode date, the previous six rendered messages (never later ones, so the text cannot foreshadow later events), the message's events as structured fields, the required mentions (values and their allowed aliases from the family lexicon), the forbidden values (every other lexicon value of the family), a persona and register, and a discourse requirement for corrections ("must signal that an earlier statement was wrong") and for changes ("must signal that the state changed"). Fillers get a topic that touches no family predicate.

**Output checks**, by program, before a message is accepted:

- every required value appears, as a normalised string or a listed alias;
- no forbidden value appears;
- no meta-language (a fixed pattern list including "event", "claim", "supersed", "version", "correction:");
- length within bounds.

A failed message is re-rendered with a new seed, up to three attempts, and then replaced by a deterministic template sentence from the family skeleton. Attempts and fallbacks are logged per family; a family whose fallback rate exceeds 10% **[assumption]** is revised before the audit.

**Reproducibility.** Sampling uses a fixed seed per message, but rendering is not guaranteed to be bit-reproducible across hardware. The rendered text is therefore part of the frozen dataset and released with it; every label is recomputable from the event log alone.

## 8. Audit protocol

T016 runs the audit; this section fixes its protocol.

- **Sample.** Per scenario family, 5 sequences drawn with a fixed seed from the generated pool, stratified over revision-density levels. From each, one window of 30 consecutive messages after the setup episode is audited (random start). Questions come from one schedule only, the sequence's primary schedule: $A(20,d)$ for $\rho=10$ and $U(10)$ for the other density levels. A 30-message window holds about 3 of the 20 read points of $A(20,d)$ and about 11 questions, which would give about 1,100 questions over 100 windows; the audit therefore takes a seeded sample of at most 5 of the window's questions, always including both members of any pair, for at most 500 questions per annotator. Windows bound the effort; annotators see the 10 preceding messages as read-only context. The plan asks for "at least 5 sequences per template family, judging per message"; auditing one window per sequence is this document's reading of that requirement (open question 4).
- **Annotators.** One author and one person not involved in building the system (chosen in phase 1), working independently. Both see the rendered text, the window's events in a readable form and the gold answers of the questions; neither sees the other's labels.
- **Labels per message.** Exactly one of: `agree`; `missing` (an event is not expressed); `extra` (the text expresses a state proposition not in the log, including any state content in a filler); `wrong-value`; `wrong-attribution` (speaker, function, report mode or polarity differs, for example an offer rendered as a confirmation); `wrong-time` (valid time wrong, or a change rendered as a correction or the reverse); `unnatural` (meaning right, English unacceptable; reported, not counted as a mismatch). **Per question:** `agree`, `gold-wrong`, `ambiguous`, `anchor-unidentifiable`.
- **Calibration.** A written guide with ten worked examples, piloted on two development-family windows that are not counted.
- **Statistics.** Cohen's κ on the binary label (any mismatch vs `agree`) and on the full label set; raw disagreement rate; prevalence of mismatches; all per family and overall, with 95% intervals from a bootstrap over windows. Mismatches are expected to be rare, which depresses κ at high raw agreement (the prevalence effect), so positive and negative specific agreement are reported as well.
- **Adjudication.** Disagreements are resolved by discussion; the adjudicated label is final.
- **Decision rule.** A family with an adjudicated mismatch rate above 5% of messages **[assumption]**, or the same mismatch three or more times, is fixed in T015 (lexicon, skeletons, rendering prompt) and re-audited with fresh windows, or excluded with the reason recorded. The overall adjudicated mismatch rate is reported in the paper as the label-noise estimate of the controlled sequences (plan section 6.9, uncertainty by source).
- **Effort.** 20 families × 5 windows × 30 messages = 3,000 messages and at most 100 windows × 5 = 500 questions per annotator; at 8 s per message and 20 s per question **[assumption]**, about 6.7 + 2.8 ≈ 9.5 hours each, 19 person-hours in total, within the annotation estimate of plan section 9.4.

Reading held-out text in the audit is not a run of any system and does not touch the preregistration rule; fixes it triggers concern data validity, not system results.

## 9. Outputs per sequence and the metrics that consume them

One directory per sequence. Only `messages.jsonl` and the question texts, delivered at their read versions, are visible to systems; every other file is gold, used only on the scoring side or injected by `eval/engines/oracles/` in labelled gold-graph experiments (D013 gold sentinel). The adapter in `src/grace/eval/datasets/benchmarks/changeseq.py` maps the files to the record contracts owned by T001.

| Output | Content | Consumed by (plan section 6.7 unless stated) |
| --- | --- | --- |
| `messages.jsonl` | ID, version, episode, speaker, timestamp, text | Input to every system. Denominators of per-message rates. Token counts for the cost ledgers and the maintenance surface (sections 8.1–8.3). Memory layer: whether the cited span entails the claim |
| `events.jsonl` (event log) | Primitive events per message, with macro ID, intended type and focus binding | Source of all gold below; the audit (section 8); the realised change mix reported per cell |
| `entries.jsonl` and `graph.trig` (gold claim graph) | All entries with version stamps, so $G_t$ is the set of entries stamped $\le t$; RDF serialisation validated against the T014 shapes | Memory layer: claim precision, recall and F1 (full recall is measurable here, unlike the sampled segments of natural data); accuracy of the attribution and time fields; share of restatements counted as independent evidence (`derived` attributions); structural validation pass rate (must be 100% on gold). Injected by `oracles/` for ablation A and C on gold graphs |
| `bindings.jsonl` and `reference.jsonl` | Every binding; canonical $(\mathrm{ans},\mathrm{wit},\mathrm{ev})$ and fingerprints at each version where they change | Pipeline layer: agreement of views with full recomputation against the event log; view hit rate (which bindings could serve each question); the cross-check with compiled re-query (section 6.4) |
| `labels.jsonl` (per-message per-binding staleness) | Answer-stale, citation-stale, change type and sub-kind for every (message, binding) | Pipeline layer: precision and recall of staleness decisions against the event-log reference, answer and citation staleness separated; with the graph reference (read-time re-query on the system's own graph), decision misses separated from extraction-induced misses; share of stale content entering the prompt. Stratification of ablation A by change type. Maintenance surface: the necessary rebuilds give the oracle-invalidation cost floor (section 8.3) |
| `schedules/<name>.jsonl` (read schedule, questions, gold answers) | Read points; per question its text, type, target binding, $(\tau,\kappa)$, gold answer set, outdated values, `premise_outdated`, expected abstention, pair ID, and the question-level change-type label `change_types` / `change_type` (section 5) that the adapter writes into the contract's `labels` | LLM layer: Acc (normalised set match as primary scorer, the blind judge as secondary); stale-value use (outdated values, presupposition questions); correct-abstention rate; paired correctness on late corrections and known-then / seen-from-now pairs (ablation B readout, plan section 7.3); attribution probes for RQ1 support (V4 and V6 after offers, guard-blocked writes) |
| Witness sets and gold evidence (in the schedule records) | Minimal witnesses and evidence message IDs per gold answer | Pipeline layer: evidence recall (strict and lenient) and full hit; LLM layer: ungrounded-answer rate |
| `meta.json` | Scenario family, split, cell parameters, seeds, generator SHA, renderer snapshot and prompt hash, realised counts per type, checksums | Stratified reporting by revision frequency and reads per history; clustering by scenario family (section 6.9); axes of the maintenance surface (section 8.3) |
| `render_log.jsonl` | Attempts, check failures, fallbacks | Validity reporting (section 6.4). Not the "rendering-check failure rate" of section 6.7, which concerns GRACE's view rendering |
| Audit records (T016, under `docs/research/`) | Labels, κ, disagreement, adjudication | Validity (section 6.4); label noise (section 6.9) |

Answer-coverage upper bound (memory layer) is 100% by construction on the controlled sequences, since every question is expressible in the fragment, and is not reported for them. JGA, slot F1, token-F1 and streaming consistency do not apply.

A dataset manifest lists every file with its SHA-256 and is bound in `configs/benchmarks/change-seq.yaml`; the data itself is written to `$PROJECT_ROOT/data/change-seq/<version>/` by the data maintainer, not by a run.

## 10. Controlled variables and sweeps

| Variable | Definition | Levels |
| --- | --- | --- |
| Change-type mix $\pi$ | Shares of macro types C1–C5 among the budgeted changes; exact counts per sequence by largest-remainder rounding, then a precondition-aware ordering (an offer precedes its acceptance, a correction targets a claim from an earlier episode) | Uniform (20% each) in every preregistered cell |
| Revision density $\rho$ | C1–C5 macros per 100 messages after the setup episode | $\{1, 3, 10, 30\}$ |
| Repeated-mention and irrelevant-update rates $\mu_6,\mu_7$ | C6 and C7 macros per 100 messages; nuisance variables | Fixed at 10 each **[assumption]**; may be set from the rough natural-distribution measurement of phase 1 (which measures data, not system results) before the T015 config is committed |
| History length $L$ | Messages | 200 in the main grids; $\{50, 100, 200, 400\}$ in the length grid. $L\le400$ keeps the full history inside the primary model's 32,768-token window at up to 40 tokens per message **[assumption]**, which the full-history baseline needs |
| Reads per history $M$ | Read points | $\{2, 5, 10, 25, 50\}$ |
| Read interval $I$ | Messages between consecutive read points | Derived: $I\approx(L-L_0)/M$ under uniform schedules; varied directly only by the Poisson schedule |

$L$, $M$ and $I$ are not independent; the grids treat $(L, M)$ as free and $I$ as derived.

**Grids.**

- **G-A (ablation A, change-type stratification).** $L=200$, $\rho=10$, uniform mix, schedule $A(20, d)$ with $d\in\{1,5\}$.
- **G-S (maintenance surface, plan section 8.3).** $L=200$ fixed; $\rho\in\{1,3,10,30\}$ × $M\in\{2,5,10,25,50\}$ under uniform schedules, 20 cells. Because reads never write, the five $M$ levels are schedules overlaid on the same sequences: messages are generated per $\rho$ level only. The $\rho=10$ sequences of G-S are the sequences of G-A.
- **G-L (length sensitivity, optional).** $L\in\{50,100,200,400\}$, $\rho=10$, $M=L/10$.

Ablation A on extracted graphs needs one ingestion pass per writer configuration; the eight strategies replay the stored change sets (D013). Under interleaved reading each schedule is its own pass for the read path (D013, separate passes per budget level).

## 11. Scenario families and split

**Candidate families** (final list fixed in T015 before any generation): train travel, flight travel, car rental, hotel stay, restaurant booking, concert tickets, music lessons, sports club, course enrolment, language tutoring, library holds, apartment search, home repair, grocery delivery, pet care, gift ordering, event planning, dental appointments, service operations (the plan's Atlas / Boreal example), meeting-room booking. Each has a multi-valued predicate, an exclusive predicate and a task type (section 2).

**Split.** 20 families: 5 development, 15 held-out.

- Families that share a non-core predicate, an entity type outside the core or a value lexicon are put in one **domain group** (for example the three travel families). The split assigns whole groups, by a seeded permutation committed before generation, so that held-out families share no domain content with development families.
- Shared across the split: the view templates, the macros, the dialogue-act inventory and the core vocabulary concepts of plan section 5.2. Held-out families therefore test predicate linking on unseen relation expressions, which plan section 10 lists as a risk ("vocabulary and templates overfit the development histories"); the per-family predicate miss rate is reported (open question 5).
- Held-out sequences may be generated, rendered and audited before the preregistration tag of T033, but no system runs on them before it.

## 12. Target sizes and power

### 12.1 Sizes

| Split | Sequences | Messages |
| --- | --- | --- |
| Held-out | 15 families × (20 at $\rho=10$ + 5 at each of $\rho\in\{1,3,30\}$) = 525 | 105,000 |
| Development | 5 families × (8 at $\rho=10$ + 2 at each other level) = 70 | 14,000 |
| G-L (optional) | 15 families × 4 lengths × 3 = 180 | 15 × 3 × (50 + 100 + 200 + 400) = 33,750 |

On the held-out G-A sequences (300 sequences, 20 per family):

- about 18 budgeted changes per sequence (3.6 per type), so per family about 70–80 instances of each change type at the read level;
- about 15 bindings per sequence **[assumption]**: two entities, each with one multi-valued predicate (V1, V3) and one exclusive predicate (V2), give 6, and three tasks (V4, V5, V6) give 9; with 20 read points this is about 300 (read point, binding) instances per sequence;
- 20 read points with 3 questions each, plus a fourth question at the read points whose special slot holds a pair: the slot rotates over three kinds, so about $20/3\approx6.7$ pairs per sequence and $60+6.7\approx67$ questions per sequence;
- per family about 1,333 questions and 133 pairs (about 67 differing and 67 controls); in total about 20,000 questions per answering arm and about 2,000 pairs, of which about 1,000 differ.

Write-side order of magnitude: at about 1,000 logical tokens per message for extraction **[assumption]**, one ingestion pass over the held-out messages is about 105M logical tokens per writer configuration, before prefix-cache reuse. T015 recomputes this with the primary model's tokenizer.

### 12.2 Power estimate

Analysis unit and clustering follow plan section 6.9: inference is at the level of scenario families, with $K=15$ held-out clusters. Assumptions:

- intraclass correlation of binary outcomes within a family $\rho_{\text{icc}}=0.05$ **[assumption]**;
- between-family standard deviation of a per-family paired difference in miss rate $\sigma_d=0.10$ **[assumption]**;
- for answer accuracy: between-family standard deviation of the paired difference $\sigma_b=0.03$, and question-level discordance $\psi=0.15$ **[assumption]**;
- two-sided $\alpha=0.05$, power $0.80$.

These are re-estimated on the development families before the preregistration (T033); sizes may then grow, never shrink.

**(a) Miss rate per change type** (a proportion, the precision target of ablation A). With $m$ instances per family, design effect $\mathrm{DE}=1+(m-1)\rho_{\text{icc}}$ and effective size $n_{\text{eff}}=Km/\mathrm{DE}$, the 95% half-width at the worst case $p=0.5$ is

$$
h=1.96\sqrt{\frac{p(1-p)}{n_{\text{eff}}}}.
$$

With $m=80$: $\mathrm{DE}=4.95$, $n_{\text{eff}}=1200/4.95=242$, $h=0.063$. With $m=70$: $\mathrm{DE}=4.45$, $n_{\text{eff}}=236$, $h=0.064$. As $m\to\infty$, $n_{\text{eff}}\to K/\rho_{\text{icc}}=300$ and $h\to0.057$: **the number of families, not the number of sequences, bounds precision**. More sequences per family buy little beyond $m\approx80$; more families would.

**(b) Paired difference in end-to-end miss rate between two strategies** (the RQ2 narrowing condition on extracted graphs: claim-pattern level against the citation-based strategies). A cluster-level paired $t$-test on the $K$ per-family differences detects

$$
\delta_{\min}=(t_{0.975,K-1}+t_{0.80,K-1})\frac{\sigma_d}{\sqrt K}=(2.145+0.868)\frac{0.10}{\sqrt{15}}=0.078 .
$$

On types C2–C4, citation-based strategies miss by construction on the graph and claim-pattern strategies miss only through extraction, so the expected difference is several times $\delta_{\min}$ unless extraction errors dominate, which is exactly the narrowing condition. As a sensitivity analysis, a two-sided sign test over 15 families needs at least 12 families in one direction ($p=0.035$); 11 gives $p=0.118$.

**(c) Over-marking rate** (claim-pattern against predicate level, the RQ2 overturn condition). The denominator is the fresh instances: of the about 300 (read point, binding) instances per sequence (15 bindings × 20 read points, section 12.1), all but the stale ones, so precision is better than in (a) at equal $\rho_{\text{icc}}$.

**(d) Answer accuracy, template serialisation against LLM rendering** (ablation C, the premise of RQ3). The variance of a per-family mean paired difference is $\sigma_b^2+\psi/m_q$ with $m_q\approx1{,}333$ questions per family: $0.0009+0.15/1333=0.0009+0.000113=0.001013$, a standard deviation of $0.0318$, so

$$
\delta_{\min}=3.013\times\frac{0.0318}{\sqrt{15}}=0.025,
$$

about 2.5 accuracy points. Again $\sigma_b$ dominates and additional questions add little.

**(e) Known-then / seen-from-now pairs.** About 67 differing pairs per family (section 12.1), about 1,000 in total; at 70% paired accuracy, $\mathrm{DE}=1+66\times0.05=4.3$, $n_{\text{eff}}=15\times67/4.3=234$, half-width $1.96\sqrt{0.21/234}\approx0.059$. Reported descriptively, as support for ablation B.

**(f) Maintenance surface.** Cost is nearly deterministic given the events; with 75 sequences per $\rho$ level and a per-sequence coefficient of variation of 0.2 **[assumption]**, the relative standard error of a cell mean is about 2.3%.

On gold graphs no power analysis is needed: zero misses of claim-pattern strategies is guaranteed by the proposition of plan section 3.4, and the miss rates of citation-based strategies follow from the configured mix (plan section 6.4). Gold-graph runs are correctness checks and over-marking measurements.

## 13. Comparison with other generators

Cells are taken from plan section 2.1 and `docs/research/literature.md`; "not established" means the reading so far does not settle the point, and it is checked against the original before the paper cites it.

| Work | Surface and speakers | Change kinds | Ground-truth granularity | Witnesses | Read placement | Bitemporal pairs |
| --- | --- | --- | --- | --- | --- | --- |
| StateMemBench (StateMem) | Synthetic event programs | Anti-update probes; 322 graded probes | Per probe | Not established | Not established | No (plan section 2.1) |
| StateChangeBench (StateGraph) | 50 author-constructed cases | One new observation per case, stratified by cascade depth | Gold status per state | Not established | One observation, then read | No |
| Deng et al. | Multi-session personal memory; controlled revision generator | Revisions; speaker misattribution | Not established | Not established | Not established | No |
| STALE | Premise-resistance probes | Outdated premises | Per probe | Not established | Not established | No |
| MemShift | Template-synthesised worlds | Source revision and redefinition; records entering scope | Gold value or status per item at maintenance checkpoints (answer level only) | Oracle dependency sets | Checkpoints at fixed offsets | Not established |
| MemDerive | Views over database tables, template-synthesised | Explicit and implicit changes, aggregation | Datalog gold per view | Minimal why-provenance witnesses | Not established | Not established |
| HaluMem | Synthetic multi-session dialogue | Updates with links to replaced memories | Per-session memory points and update labels | — | Session by session | Not established |
| FactConsolidation | Concatenated counterfactual edit pairs; no dialogue, speakers or attribution | Fact edits | Per question | — | Chunks, then questions | No |
| **This design** | Two-party dialogue rendered by an outside model; speaker, communicative function and report mode on every statement | Seven types including insertion-driven ones (new match, negation hit, count) and guard-blocked writes; change vs correction | Every (message, binding), answer and citation staleness separately, any $(r_0,r)$ pair | Minimal witnesses and evidence per answer | Interleaved, controlled $M$ and $I$; every version readable | Yes, with control pairs |

**What is not new.** Program-generated ground truth (StateMemBench, MemShift, MemDerive), insertion-driven staleness (MemShift's records entering scope, MemDerive's implicit changes) and why-provenance witnesses (MemDerive) have precedent. **What this design adds**: dialogue with attribution and the guard-blocked probes; two-level staleness labels per message and binding; bitemporal paired questions with change and correction distinguished; interleaved reading as a controlled variable; ground truth computed independently of the system's compiler; and the family-level split with a two-annotator audit.

## 14. Change control and open questions

**Change control.** Until T015 starts generating held-out sequences, changes to this document go through ordinary PRs. After the first staleness result (E003 or later), any change is a deviation: it is recorded with date and reason in a "Deviations" section appended here and in the experiment log, as plan section 6.9 requires for the preregistration.

**Open questions for the plan owner and dependent tasks.**

1. **V4 semantics.** Plan section 5.4 calls the view "original constraints of a task". This design defines it as the constraints the user has requested and not revised, so a user's own revision replaces the value and an offer never does. If "original" should mean the first requested value regardless of later user revisions, V4 drops the currently-accepted condition and selects the earliest request.
2. **Valid end of superseded claims.** The supersession entry of plan section 3.2 has no valid-time field, so the past membership of a multi-valued predicate is not determined. Historical questions are restricted to exclusive predicates until T014 decides whether supersession events carry a valid end.
3. **Renderer.** Which model (outside every evaluated family and different from the judge) renders the text; chosen in phase 1 with the other model choices.
4. **Audit windows.** Whether auditing one 30-message window per sampled sequence satisfies "at least 5 sequences per template family" in plan section 6.4.
5. **Held-out vocabulary.** Whether held-out families may use predicates outside the core vocabulary (this design: yes, to test predicate linking), or whether all predicates should come from a shared list.
6. **Supersession without a replacing claim and the guard.** Whether the attribution guard covers supersession without a replacing claim (section 3.2, G2(ii)). If it does not, both `m-remove` and the multi-valued variant of `m-correct` are disabled: no claim on a multi-valued predicate is ever superseded, so V1 and V3 lose their C1 and C5 strata. C1 and C5 are then realised only on exclusive predicates (V2, V4 and the catalogue join of V6), and the change-type stratification of ablation A is reported for V1 and V3 without those two types.
7. **Local conditions the IR must express.** The fragment's attribution constraint names speaker and function; the views also need own report mode and positive polarity on the attribution, and V2 needs "no valid end" on the claim. T017 must express these as local filters of the pattern; otherwise the view semantics of section 6.2 change and this document is revised before T015.
8. **Terminology in the plan.** Plan sections 6.4 and 6.9 say "template family" for what this document calls a scenario family (the unit of the split, the audit sample and clustering), while section 5.4 uses the same words for the view templates. Should the plan owner rename the term in sections 6.4 and 6.9 (English and Chinese) to "scenario family", to match this document and D013's "one function per template family", which refers to view templates?
