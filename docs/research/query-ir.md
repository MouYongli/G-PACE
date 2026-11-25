# Query Intermediate Representation

This document specifies the restricted query language of GRACE: its typed intermediate representation (IR), the text grammar, the type rules, and how the compiler maps each construct to SPARQL over the claim graph. Terms follow plan sections 3.2 to 3.5 and 5.3; the RDF encoding is the "Claim graph" section of `docs/research/contracts.md`.

Code: `src/grace/context/pipeline/query/` (`ir.py` types and type checker, `grammar.py` parser and printer, `compile.py` compiler, `execute.py` execution, `result.py` results). Task: T017.

## 1. What the fragment contains

The atom is the **claim pattern** `(s, p, o, scope)[u, f]`. The first four positions match a claim and are constants or variables; the bracket is an optional attribution constraint that requires an attribution on that claim with speaker `u` and communicative function `f`. By default that attribution must also be the speaker's own statement (report mode own), positive and not derived, so quotes, hypotheticals, denials and inferred attributions do not satisfy the constraint (plan 3.3, user decision of 2026-11-25 on finding F1 of T015). A query may relax each default explicitly, and only relax it: `[u, f, mode=_]` accepts any report mode, `polarity=_` any polarity, `derived=_` derived attributions too (section 2). Certainty is not constrained. A query combines claim patterns with exactly the six operations of plan 3.3:

| Operation | IR type | Text form |
| --- | --- | --- |
| Filter against a constant or a claim's valid time | `Filter` | `FILTER(?x <= "20:45:00"^^time)`, `FILTER(start(?c) >= "2023-06-01"^^date)` |
| Join over one to three claim patterns | `Query.where` | `{ (…) . (…) . (…) }` |
| Negation: one non-nested NOT EXISTS over one pattern sharing a variable | `NotExists` | `NOT EXISTS { (…) [user, accept] FILTER(…) }` |
| Distinct count, optionally grouped by the selected variables | `CountDistinct` | `SELECT ?p COUNT(DISTINCT ?i)` |
| Latest confirmed state, the maximum by version or valid time | `Latest` | `LATEST BY version OF ?c`, `LATEST BY valid OF ?c` |
| Provenance expansion: witnesses and evidence of every answer | `Query.provenance` | on by default; `WITHOUT PROVENANCE` turns off the evidence query |

Every query also carries its temporal parameters `AT(known=…, valid=…, state=…)`:

- `known` is the cut-off version. `known=r` (the default) binds it to the version being read, a moving cut-off; an integer fixes it, a time-travel read. In SPARQL it is always the placeholder `%r%` (section 4).
- `valid` is a world time `d` (`xsd:date` or `xsd:dateTime`). Only claims not known to lie outside their valid interval at `d` match.
- `state=current` (default) adds the built-in "currently accepted" negation to every claim pattern; `state=historical` adds the weaker form that excludes only claims superseded by a correction, so a claim superseded by a change stays visible as past state.

## 2. Text grammar

```ebnf
Query      ::= "SELECT" Select "WHERE" Group Latest? At? Provenance? "TEMPORARY"?
Select     ::= Var+ | Var* "COUNT" "(" "DISTINCT" Var ")"
Group      ::= "{" Pattern ( "." Pattern ){0,2} "."? Item* "}"      (* items and patterns may interleave *)
Item       ::= Filter | Negation
Negation   ::= "NOT" "EXISTS" "{" Pattern "."? Filter* "}"
Pattern    ::= "(" Subject "," Predicate "," Object ( "," Scope )? ")" Constraint? ( "AS" Var )?
Constraint ::= "[" ( Entity | Var | "_" ) "," ( Function | "_" ) ( "," Relax )* "]"
Relax      ::= ( "mode" | "polarity" | "derived" ) "=" "_"            (* each at most once *)
Subject    ::= Entity | Var
Predicate  ::= Name | Var
Object     ::= Entity | Var | Literal
Scope      ::= "_" | "default" | String | Var
Filter     ::= "FILTER" "(" Left Op Right ")"
Left       ::= Var | "start" "(" Var ")" | "end" "(" Var ")"
Op         ::= "=" | "!=" | "<" | "<=" | ">" | ">="
Right      ::= Literal | Entity | "now" "(" Integer? ")"            (* now(…) only before absolutize *)
Latest     ::= "LATEST" "BY" ( "version" | "valid" ) "OF" Var
At         ::= "AT" "(" AtArg ( "," AtArg )* ")"
AtArg      ::= "known" "=" ( Integer | "r" ) | "valid" "=" Literal | "state" "=" ( "current" | "historical" )
Provenance ::= "WITH" "PROVENANCE" | "WITHOUT" "PROVENANCE"
Var        ::= "?" [A-Za-z][A-Za-z0-9_]*                            (* "?_…" is reserved for the compiler *)
Entity     ::= [A-Za-z0-9_][A-Za-z0-9_-]* | "<" percent-encoded ID ">"
Name       ::= [A-Za-z][A-Za-z0-9_]*                                (* a vocabulary predicate *)
Function   ::= "request" | "offer" | "accept" | "reject" | "confirm" | "inform" | "commit" | "question"
Literal    ::= String ( "^^" Datatype )? | Integer | "true" | "false"
Datatype   ::= "string" | "integer" | "boolean" | "date" | "dateTime" | "time"
```

Keywords are case-insensitive; `#` starts a comment. Literals must be in the canonical lexical form of their datatype (the same rule as claim objects in the contract). `AS ?c` labels the matched claim node so that `start(?c)`, `end(?c)` and `LATEST … OF ?c` can refer to it; a label is never an answer variable. `to_text` prints the canonical form, and `parse(to_text(q)) == q`; relaxed defaults are printed in the order `mode`, `polarity`, `derived`.

**Attribution defaults.** In the IR, `AttributionConstraint` has three fields besides speaker and function: `report_mode` (default `ReportMode.OWN`), `polarity` (default `Polarity.POSITIVE`) and `derived` (default `False`). `None` relaxes a field to "any" and is written `mode=_`, `polarity=_`, `derived=_`. Any other value (a constraint that requires a quote or a denial) is rejected by the parser and the type checker, because the fragment only lets a query relax the defaults.

Examples, from the running examples of plan 3.5:

```text
# The accepted train and its arrival time (plan 5.3)
SELECT ?train ?arr WHERE {
  (request1, selectedService, ?train) [user, accept] .
  (?train, scheduledArrival, ?arr)
}

# Candidates offered and not yet accepted
SELECT ?train WHERE {
  (request1, selectedService, ?train) [system, offer]
  NOT EXISTS { (request1, selectedService, ?train) [user, accept] }
}

# Number of instruments Melanie plays
SELECT COUNT(DISTINCT ?i) WHERE { (melanie, playsInstrument, ?i) }

# The current choice
SELECT ?train WHERE { (request1, selectedService, ?train) [user, accept] AS ?c }
LATEST BY version OF ?c

# Where Lina lived on 1 June 2022, as known at version 7
SELECT ?city WHERE { (lina, livesIn, ?city) }
AT(known=7, valid="2022-06-01"^^date, state=historical)
```

## 3. Type rules

The parser rejects syntax outside the fragment with a message that names the construct; `ir.typecheck` rejects every IR that the types can build but the fragment forbids. Both raise `QueryTypeError`, and the type checker reports all problems at once.

| Rejected | Message names |
| --- | --- |
| More than three positive claim patterns, or none | "joins are limited to 3 claim patterns" |
| Property paths (`p/q`, `p+`, `p*`, `p\|q`, `^p`), triple patterns outside a claim pattern | "property paths", "triple patterns" |
| Aggregates other than `COUNT(DISTINCT ?x)` (`SUM`, `AVG`, `MIN`, `MAX`, `SAMPLE`, `GROUP_CONCAT`, `COUNT(?x)`, `COUNT(DISTINCT *)`) | the aggregate |
| Comparison with the time of reading (`now(…)`, `AT(valid=NOW)`) | "time of reading" |
| Comparison between two variables; disjunction or conjunction inside one `FILTER` | "only with constants", "one comparison per FILTER" |
| `OPTIONAL`, `UNION`, `MINUS`, `BIND`, `VALUES`, `GRAPH`, `SERVICE`, `ORDER`, `LIMIT`, `GROUP`, `HAVING`, nested groups | the keyword |
| Nested negation, a negation over more than one pattern, a second negation, a negated pattern sharing no variable with the positive part | the rule |
| A selected, counted or filtered variable not bound by a positive pattern; a variable bound only inside the negation in the answer | the variable |
| A variable used as a predicate or scope and also in another position | "used both as" |
| An entity compared with `<`, `<=`, `>`, `>=`; an entity variable compared with a literal; `start`/`end` compared with anything but an `xsd:date` or `xsd:dateTime` | the rule |
| `COUNT` together with `LATEST`; `LATEST` naming no positive label; an attribution constraint with neither speaker nor function | the rule |

**Relative time.** A task with relative time ("in the last week") is written with `now(-7)` and parsed with `check=False`; `compile.absolutize(query, read_time)` replaces every `now(offset)` with the absolute date `read_time + offset` days and marks the query `TEMPORARY`. A temporary query runs only while answering and is never stored as a view (plan 3.3).

## 4. Compilation

`compile_query(query, mode)` type-checks the query, labels unlabelled patterns (`?_c0`, `?_c1`, `?_c2`, negated `?_n`) and emits three SPARQL texts. Compilation is deterministic: the same query and serialisation mode always give the same text. Vocabulary terms use the prefixes `ClaimStore.query` predeclares (`g:`, `gp:`, `gf:`, `rdf:`, `prov:`, `oa:`).

### Parameters

| Placeholder | Replaced by | When |
| --- | --- | --- |
| `%r%` | the integer cut-off version | by `ClaimStore.query`, at execution (contract, "Store rules"; plan 5.3) |
| `%k<i>%` | the IRIs of the members of the entity-equivalence class of the i-th entity constant at the cut-off | by `CompiledQuery.bind`, at execution |
| `%claims%` | the IRIs of the witness claims | in the evidence query, at execution |

`%r%` is neither a SPARQL variable (a filter over an unbound variable drops every row) nor a hard-coded constant (whether the cut-off is fixed or moves decides whether a view can go stale). A query with `known=4` and one with `known=r` compile to the same text; execution chooses the cut-off.

### Main query

For each positive claim pattern labelled `?c`:

```sparql
?c rdf:subject S ; rdf:predicate gp:p ; rdf:object O ; g:knownFrom ?_v_c .     # rdf11
?c rdf:reifies <<( S gp:p O )>> ; g:knownFrom ?_v_c .                            # rdf12
FILTER(?_v_c <= %r%)
?c g:scope "work" .                       # scope constant; a variable binds; `default` is
FILTER NOT EXISTS { ?c g:scope ?_sc_c }   # … this form; `_` adds nothing
?_a_c g:about ?c ; prov:wasAttributedTo U ; g:function gf:f ;                     # [u, f]
      g:reportMode g:OwnStatement ; g:polarity g:Positive ;                       # defaults; a relaxed
      g:derived "false"^^xsd:boolean ; g:knownFrom ?_w_c .                        # one drops its triple
FILTER(?_w_c <= %r%)
FILTER NOT EXISTS { ?_s_c g:supersedes ?c ; g:knownFrom ?_sv_c . FILTER(?_sv_c <= %r%) }   # current
FILTER NOT EXISTS { ?_s_c g:supersedes ?c ; g:kind g:Correction ;
                    g:knownFrom ?_sv_c . FILTER(?_sv_c <= %r%) }                            # historical
```

Entity constants become `VALUES ?_k<i> { %k<i>% }`. The state negation is the contract's "currently accepted" form; it does not test the kind of a supersession for current-state queries.

**Valid time.** With `AT(valid=d)` each claim must not be known to be outside `[start, end)` at `d`: no `g:validFrom` later than `d`, no own `g:validUntil` at or before `d`, and, when the claim has no own end, no effective end at or before `d`. The **effective valid end** follows the contract: the claim's own end, else the `valid_end` of the earliest change supersession stamped at most the cut-off that states one, else open. An unknown start or end therefore never excludes a claim. Comparisons across `xsd:date` and `xsd:dateTime` are undefined in SPARQL and are treated as unknown.

**Filters.** `FILTER(?x op literal)` compiles verbatim; `?x = E` and `?x != E` become `IN` and `NOT IN` over the class members of `E`. `start(?c) op d` holds only if the claim has a start that satisfies it. `end(?c) op d` uses the effective valid end; an open end is later than every time, so `>`, `>=` and `!=` hold for it and `<`, `<=`, `=` do not.

**Negation.** `NOT EXISTS { … }` wraps the triples of the negated pattern with the same version filters, state negation and valid-time filter as a positive pattern, plus its local filters. Negation is not nested from the user's point of view; the built-in state negation inside it is generated by the compiler. Variables that occur only in the negated pattern are existential.

**Projection.** The main query projects the answer variables, then the witness columns: the claim node of every positive pattern and the attribution node of every attribution constraint. It never joins evidence. For `LATEST BY version` it also binds `?_key` to the version at which the pattern became matched, the later of the claim's and the constraining attribution's version stamps ("latest confirmed": a later acceptance of an older offer counts at the version of the acceptance); for `LATEST BY valid` it binds `?_key` to the claim's `g:validFrom` (claims without one cannot be latest by valid time). `ORDER BY DESC(?_key)` documents the intent; the selection itself is done in `execute.py`: it first selects the latest claim of the labelled pattern, whose key is the maximum `?_key` over its rows (the latest version at which it was confirmed), and then keeps every row of that claim, so that a restated claim keeps its earlier witnesses; ties keep every tied claim.

**Count query.** For `COUNT(DISTINCT ?x)` the compiler also emits `SELECT ?g… (COUNT(DISTINCT ?x) AS ?_count) WHERE { same body } GROUP BY ?g…`. Execution derives the count from the members of the main query, because it must return their witnesses; the tests check that both agree on every fixture version.

**Evidence query.** The second query fetches the evidence links of the witness claims that are visible at the cut-off:

```sparql
SELECT ?_claim ?_evidence ?_message ?_start ?_end WHERE {
  VALUES ?_claim { %claims% }
  ?_evidence g:supports ?_claim ; prov:wasDerivedFrom ?_message ; g:knownFrom ?_ev .
  FILTER(?_ev <= %r%)
  OPTIONAL { ?_evidence oa:hasSelector ?_sel . ?_sel oa:start ?_start ; oa:end ?_end . }
}
```

Evidence is returned as unified evidence IDs (`message_id`, or `message_id#char=start,end` for a span), the same form as `memory/history/spans.py`.

## 5. Answers, witnesses and evidence

`execute(compiled, store, version)` reads at cut-off `known` if fixed, else at `version`; a cut-off after the version read is refused. Witnesses follow plan 3.4:

| Construct | Witness |
| --- | --- |
| Positive join | Every row is one witness: the claims of the positive patterns and the attributions satisfying their constraints. An answer keeps all its minimal witnesses (why-provenance); a witness that contains another is dropped, which happens when two patterns bind the same claim. |
| Negation | Contributes nothing; the negated pattern is not projected. |
| Distinct count | One witness: the union of the minimal witnesses of all counted members. A count over nothing is 0 with no witness (no grouping) or no row (grouping). |
| Latest state | All witnesses of the selected claim: every row whose labelled claim has the maximum key, including rows of earlier confirmations of that claim. |

The evidence of an answer is the union of the evidence of the claims in its witnesses. Attributions in a witness contribute no evidence of their own, because plan 3.4 defines evidence over claims; an acceptance is cited through the evidence link the writer adds to the accepted claim (plan 5.3: "one answer depends on two messages at once").

`QueryResult.fingerprints()` returns SHA-256 fingerprints of the canonical answers, witnesses and evidence, the inputs of read-time re-query and of answer- versus citation-staleness (plan 3.4).

**Scope notes.** `result.scope_note(result)` returns "Counted within the scope observed up to version r." for counts and "No matching claim within the scope observed up to version r." for empty results, `None` otherwise. It is generated when the result is read and is not part of the result record or of any fingerprint, so it never makes a view stale.

**Entity equivalence.** Queries are evaluated on class representatives (contract, "Claim graph"): an entity constant matches every member of its class at the cut-off, and entity answers are reported as the representative (the smallest member ID). See open question 1.

**Time-travel stability.** Every entry the compiled query can touch, including supersessions, evidence links and entity equivalences, is filtered by `%r%`. A read with a fixed cut-off `r0` therefore returns the same answers, witnesses and evidence on `G_r` for every `r ≥ r0` (plan 3.3); the integration tests check this for every query of the suite at every version of the fixture history.

## 6. What the fragment cannot express

- Optional parts, unions and disjunctive filters; property paths and transitive closure; more than three joined claim patterns.
- Arithmetic, date arithmetic and comparisons between variables, including "the train arrives before the requested time" (both sides are variables). A rule template or the planner must bind one side to a constant first.
- Aggregates other than distinct counting; maximum by anything other than version or valid-time start; latest state per group.
- Negation over more than one pattern or nested negation; negation that shares no variable with the positive part.
- Attribution constraints that require a non-default report mode or polarity (only quotes, only hypotheticals, only denials) or only derived attributions; constraints on certainty. A constraint can only keep or relax its defaults (section 2).
- Comparisons with the time of reading in stored views.

## 7. Open questions

1. **Joins across merged entities.** Constants and answers use class representatives, but a join variable still compares node identity, so a join between two members of one class is not made. Exact evaluation needs either canonicalised claim nodes or per-variable class expansion. Entity merges already invalidate every view of the history (plan 5.2), so this affects only reads after a merge.
2. **Polarity of attributions in constraints (resolved 2026-11-25).** The user decided on finding F1 of T015's cross-check (PR #72) that `[u, f]` by default requires an own, positive, not derived attribution, and that a query may relax these defaults explicitly (plan 3.3). Section 2 ("Attribution defaults") and section 4 implement this.
3. **Dependency patterns.** These were implemented by T019 in `views/dependencies.py` and matched in `views/staleness/matching.py`, not in `pipeline/query/patterns.py`. Those modules still match an attribution constraint on speaker and function only and do not record the relaxed defaults in a dependency record. The change matcher therefore also fires on quoted, hypothetical, negative or derived attributions that the compiled query no longer accepts. That over-marks, which is sound (no misses), but it is less precise; the follow-up belongs to the owner of `views/`.
