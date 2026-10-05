"""
AI SaaS Growth Intelligence — Master Data Generator
=====================================================
IMPORTANT: every row is SIMULATED (fixed seed, so the output is identical on every run).
No real company's data is used. The generator bakes in the assumptions listed below
(channel quality, Rewrite's effect on churn, the A/B treatment effect), so the analysis
shows that the pipeline recovers those assumptions — it is not evidence about a real product.

Generates all data for both parts in one run:

  Part 1 — Funnel & Retention Analysis
    tables : users, events, sessions, subscriptions, feature_usage
    db     : ai_saas.db
    csvs   : users.csv, events.csv, sessions.csv,
             subscriptions.csv, feature_usage.csv

  Part 2 — A/B Test: Rewrite-First Onboarding
    tables : ab_users, ab_events, ab_sessions
    db     : ab_test.db
    csvs   : ab_users.csv, ab_events.csv, ab_sessions.csv

Run:
    python data_generator.py

Output directory: ./data/
"""

import random, csv, os, sqlite3
from datetime import datetime, timedelta

random.seed(99)

DATA_DIR = "./data"
os.makedirs(DATA_DIR, exist_ok=True)

# ──────────────────────────────────────────────────────────────────────────────
# SHARED HELPERS
# ──────────────────────────────────────────────────────────────────────────────
def rand_date(start, end):
    return start + timedelta(days=random.randint(0, (end - start).days))

def weighted_choice(items, weights):
    return random.choices(items, weights=weights, k=1)[0]

def write_csv(path, rows):
    if not rows:
        return
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    print(f"  {os.path.basename(path)}: {len(rows):,} rows")


# ══════════════════════════════════════════════════════════════════════════════
# PART 1 — FUNNEL & RETENTION ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════
print("\n── Part 1: Funnel & Retention Analysis ────────────────────────────────")

# ── Config ────────────────────────────────────────────────────────────────────
P1_N_USERS   = 30_000
P1_START     = datetime(2021, 1, 1)
P1_END       = datetime(2025, 12, 31)

CHANNELS     = ["organic_search", "paid_google", "paid_meta", "referral", "direct"]
CHANNEL_W    = [0.30, 0.22, 0.18, 0.20, 0.10]
PLANS        = ["free", "pro", "enterprise"]
PLAN_W       = [0.60, 0.30, 0.10]
COUNTRIES    = ["IN", "US", "GB", "DE", "AU", "CA", "SG", "BR"]
COUNTRY_W    = [0.35, 0.25, 0.10, 0.08, 0.07, 0.06, 0.05, 0.04]
AGE_GROUPS   = ["18-24", "25-34", "35-44", "45-54", "55+"]
AGE_W        = [0.15, 0.40, 0.28, 0.12, 0.05]
FEATURES     = ["rewrite", "summarize", "generate", "analyze", "translate"]

# ASSUMPTION: causal effect of feature adoption on churn probability (multiplier on base churn rate).
# Rewrite is simulated as the stickiest feature; translate has no retention effect.
# (So in Part 1 the Rewrite→churn link is built in as causal, not discovered.)
FEATURE_CHURN_MULT = {
    "rewrite": 0.60, "analyze": 0.77, "summarize": 0.89, "generate": 0.96, "translate": 1.00,
}

# ── Channel-specific rates ─────────────────────────────────────────────────────
CHANNEL_RATES = {
    "organic_search": {"activate": 0.87, "first_ai": 0.72, "upgrade": 0.18, "w8_retain": 0.64},
    "referral":       {"activate": 0.84, "first_ai": 0.68, "upgrade": 0.22, "w8_retain": 0.58},
    "direct":         {"activate": 0.80, "first_ai": 0.60, "upgrade": 0.15, "w8_retain": 0.50},
    "paid_google":    {"activate": 0.75, "first_ai": 0.52, "upgrade": 0.12, "w8_retain": 0.38},
    "paid_meta":      {"activate": 0.68, "first_ai": 0.42, "upgrade": 0.09, "w8_retain": 0.30},
}

PLAN_MRR = {"free": 0, "pro": 999, "enterprise": 4999}   # INR per month

print("  Generating Part 1 users & events...")
p1_users, p1_events, p1_sessions = [], [], []
p1_subscriptions, p1_feature_usage = [], []
eid = sid = sub_id = fuid = 1

for i in range(1, P1_N_USERS + 1):
    channel   = weighted_choice(CHANNELS, CHANNEL_W)
    plan      = weighted_choice(PLANS, PLAN_W)
    country   = weighted_choice(COUNTRIES, COUNTRY_W)
    age_group = weighted_choice(AGE_GROUPS, AGE_W)
    signup    = rand_date(P1_START, P1_END)
    rates     = CHANNEL_RATES[channel]

    p1_users.append({
        "user_id": i, "signup_date": signup.strftime("%Y-%m-%d"),
        "channel": channel, "plan_tier": plan,
        "country": country, "age_group": age_group,
    })

    # signed_up
    p1_events.append({"event_id": eid, "user_id": i, "event_type": "signed_up",
                      "event_date": signup.strftime("%Y-%m-%d")})
    eid += 1

    # activated
    activated = random.random() < rates["activate"]
    act_dt = None
    if activated:
        act_dt = signup + timedelta(days=random.randint(0, 2))
        if act_dt > P1_END: act_dt = signup
        p1_events.append({"event_id": eid, "user_id": i, "event_type": "activated",
                          "event_date": act_dt.strftime("%Y-%m-%d")})
        eid += 1

    # first_ai_output
    did_ai = activated and random.random() < (rates["first_ai"] / rates["activate"])
    ai_dt  = None
    if did_ai:
        ai_dt = (act_dt or signup) + timedelta(days=random.randint(0, 5))
        if ai_dt > P1_END: ai_dt = act_dt or signup
        p1_events.append({"event_id": eid, "user_id": i, "event_type": "first_ai_output",
                          "event_date": ai_dt.strftime("%Y-%m-%d")})
        eid += 1

    # invited_team
    if did_ai and random.random() < 0.20:
        inv_dt = ai_dt + timedelta(days=random.randint(1, 10))
        if inv_dt <= P1_END:
            p1_events.append({"event_id": eid, "user_id": i, "event_type": "invited_team",
                              "event_date": inv_dt.strftime("%Y-%m-%d")})
            eid += 1

    # upgraded
    if did_ai and random.random() < rates["upgrade"] and plan == "free":
        upg_dt = ai_dt + timedelta(days=random.randint(3, 30))
        if upg_dt <= P1_END:
            plan = "pro"
            p1_events.append({"event_id": eid, "user_id": i, "event_type": "upgraded",
                              "event_date": upg_dt.strftime("%Y-%m-%d")})
            eid += 1

    # feature_usage — decide which features this user adopts BEFORE churn,
    # since feature adoption is what causally affects retention below
    used = []
    if did_ai:
        n_feats = random.choices([1, 2, 3, 4, 5], weights=[0.30, 0.28, 0.22, 0.13, 0.07])[0]
        used = random.sample(FEATURES, n_feats)

    # churned (week-3 spike) — feature adoption reduces churn probability
    churned = False
    base_churn_prob = 1 - rates["w8_retain"]
    churn_mult = min([FEATURE_CHURN_MULT[f] for f in used], default=1.0)
    churn_prob = base_churn_prob * churn_mult
    if did_ai and random.random() < churn_prob:
        churn_dt = (ai_dt or signup) + timedelta(days=random.choices(
            [random.randint(7, 13), random.randint(14, 20), random.randint(21, 27),
             random.randint(28, 60), random.randint(61, 90)],
            weights=[0.10, 0.18, 0.35, 0.22, 0.15])[0])
        if churn_dt <= P1_END:
            p1_events.append({"event_id": eid, "user_id": i, "event_type": "churned",
                              "event_date": churn_dt.strftime("%Y-%m-%d")})
            eid += 1
            churned = True

    # subscriptions
    if plan != "free":
        end_dt = signup + timedelta(days=random.randint(30, 365))
        status = "cancelled" if churned and random.random() < 0.7 else "active"
        p1_subscriptions.append({
            "subscription_id": sub_id, "user_id": i, "plan": plan,
            "mrr_inr": PLAN_MRR[plan], "status": status,
            "start_date": signup.strftime("%Y-%m-%d"),
            "end_date":   end_dt.strftime("%Y-%m-%d") if status == "cancelled" else "",
        })
        sub_id += 1

    # sessions — channel quality genuinely drives how long a user stays active
    if activated:
        retained_w8 = random.random() < rates["w8_retain"]
        full_span   = max(1, (P1_END - (act_dt or signup)).days)
        if retained_w8:
            max_span = min(full_span, 120)
            n_sess   = random.randint(6, 15)
        else:
            max_span = min(full_span, random.randint(7, 54))   # last session lands before week 8
            n_sess   = random.randint(2, 6)
        for s in range(n_sess):
            sess_dt = (act_dt or signup) + timedelta(days=random.randint(0, max_span))
            if sess_dt > P1_END: continue
            feature = weighted_choice(
                ["rewrite", "summarize", "generate", "analyze", "translate", "none"],
                [0.22, 0.25, 0.28, 0.13, 0.07, 0.05])
            p1_sessions.append({
                "session_id": sid, "user_id": i,
                "session_date": sess_dt.strftime("%Y-%m-%d"),
                "session_number": s + 1,
                "ai_feature_used": feature,
                "duration_seconds": int(random.lognormvariate(5.4, 0.7)),
            })
            sid += 1

    # feature_usage rows (uses `used`, decided above, before churn)
    if did_ai:
        for feat in used:
            first_use = (ai_dt or signup) + timedelta(days=random.randint(0, 14))
            if first_use > P1_END: first_use = ai_dt or signup
            last_use  = first_use + timedelta(days=random.randint(0, 60))
            if last_use > P1_END: last_use = first_use
            usage_30d = int(random.lognormvariate(2.8, 0.9)) if feat == "rewrite" \
                        else int(random.lognormvariate(2.3, 0.8))
            p1_feature_usage.append({
                "usage_id": fuid, "user_id": i, "feature_name": feat,
                "first_used_date": first_use.strftime("%Y-%m-%d"),
                "last_used_date":  last_use.strftime("%Y-%m-%d"),
                "usage_count_30d": usage_30d,
            })
            fuid += 1

# Write Part 1 CSVs
print("  Writing Part 1 CSVs...")
write_csv(f"{DATA_DIR}/users.csv",         p1_users)
write_csv(f"{DATA_DIR}/events.csv",        p1_events)
write_csv(f"{DATA_DIR}/sessions.csv",      p1_sessions)
write_csv(f"{DATA_DIR}/subscriptions.csv", p1_subscriptions)
write_csv(f"{DATA_DIR}/feature_usage.csv", p1_feature_usage)

# Write Part 1 SQLite DB
print("  Building ai_saas.db...")
db1 = sqlite3.connect(f"{DATA_DIR}/ai_saas.db")
c1  = db1.cursor()
c1.executescript("""
DROP TABLE IF EXISTS users; DROP TABLE IF EXISTS events;
DROP TABLE IF EXISTS sessions; DROP TABLE IF EXISTS subscriptions; DROP TABLE IF EXISTS feature_usage;
CREATE TABLE users (user_id INT PRIMARY KEY, signup_date TEXT, channel TEXT, plan_tier TEXT, country TEXT, age_group TEXT);
CREATE TABLE events (event_id INT PRIMARY KEY, user_id INT, event_type TEXT, event_date TEXT);
CREATE TABLE sessions (session_id INT PRIMARY KEY, user_id INT, session_date TEXT, session_number INT, ai_feature_used TEXT, duration_seconds INT);
CREATE TABLE subscriptions (subscription_id INT PRIMARY KEY, user_id INT, plan TEXT, mrr_inr INT, status TEXT, start_date TEXT, end_date TEXT);
CREATE TABLE feature_usage (usage_id INT PRIMARY KEY, user_id INT, feature_name TEXT, first_used_date TEXT, last_used_date TEXT, usage_count_30d INT);
CREATE INDEX idx_ev_user ON events(user_id); CREATE INDEX idx_ev_type ON events(event_type);
CREATE INDEX idx_sess_user ON sessions(user_id); CREATE INDEX idx_fu_user ON feature_usage(user_id);
""")
c1.executemany("INSERT INTO users VALUES (?,?,?,?,?,?)",
    [(u["user_id"],u["signup_date"],u["channel"],u["plan_tier"],u["country"],u["age_group"]) for u in p1_users])
c1.executemany("INSERT INTO events VALUES (?,?,?,?)",
    [(e["event_id"],e["user_id"],e["event_type"],e["event_date"]) for e in p1_events])
c1.executemany("INSERT INTO sessions VALUES (?,?,?,?,?,?)",
    [(s["session_id"],s["user_id"],s["session_date"],s["session_number"],s["ai_feature_used"],s["duration_seconds"]) for s in p1_sessions])
c1.executemany("INSERT INTO subscriptions VALUES (?,?,?,?,?,?,?)",
    [(s["subscription_id"],s["user_id"],s["plan"],s["mrr_inr"],s["status"],s["start_date"],s["end_date"]) for s in p1_subscriptions])
c1.executemany("INSERT INTO feature_usage VALUES (?,?,?,?,?,?)",
    [(f["usage_id"],f["user_id"],f["feature_name"],f["first_used_date"],f["last_used_date"],f["usage_count_30d"]) for f in p1_feature_usage])
db1.commit(); db1.close()

print(f"  Part 1 complete — {len(p1_users):,} users, {len(p1_events):,} events, {len(p1_sessions):,} sessions")


# ══════════════════════════════════════════════════════════════════════════════
# PART 2 — A/B TEST: REWRITE-FIRST ONBOARDING
# ══════════════════════════════════════════════════════════════════════════════
print("\n── Part 2: A/B Test ────────────────────────────────────────────────────")

# ── Config ────────────────────────────────────────────────────────────────────
P2_N_USERS   = 6_200
P2_START     = datetime(2025, 3, 1)
P2_END       = datetime(2025, 9, 30)

# Baked-in assumptions (inputs to the simulation, not findings):
#   control first-AI rate  = CTRL_FIRST_AI_RATE  (0.365 of all users)
#   treatment first-AI rate = TREAT_FIRST_AI_RATE (0.482 of all users)
# NOTE: users only get first_ai_output if they are ALSO activated, so the realised rates
# measured from the data are 34.7% (control) and 49.9% (treatment) — see analysis.py.
# Users alternate control/treatment by user_id parity (i % 2) — a simulation shortcut for
# random assignment, not true randomisation.
CTRL_ACTIVATE_RATE   = 0.79
CTRL_FIRST_AI_RATE   = 0.365
CTRL_W4_RETAIN_RATE  = 0.448
CTRL_CHURN_W3        = 0.28

TREAT_ACTIVATE_RATE  = 0.83
TREAT_FIRST_AI_RATE  = 0.482
TREAT_W4_RETAIN_RATE = 0.541
TREAT_CHURN_W3       = 0.19

print("  Generating Part 2 experiment users...")
ab_users, ab_events, ab_sessions = [], [], []
eid2 = sid2 = 1

for i in range(1, P2_N_USERS + 1):
    variant  = "control" if i % 2 == 0 else "treatment"
    channel  = weighted_choice(CHANNELS, CHANNEL_W)
    plan     = weighted_choice(PLANS, PLAN_W)
    signup   = rand_date(P2_START, P2_END)

    act_rate = CTRL_ACTIVATE_RATE  if variant == "control" else TREAT_ACTIVATE_RATE
    ai_rate  = CTRL_FIRST_AI_RATE  if variant == "control" else TREAT_FIRST_AI_RATE
    w4_rate  = CTRL_W4_RETAIN_RATE if variant == "control" else TREAT_W4_RETAIN_RATE
    churn_w3 = CTRL_CHURN_W3       if variant == "control" else TREAT_CHURN_W3

    ab_users.append({"user_id": i, "signup_date": signup.strftime("%Y-%m-%d"),
                     "variant": variant, "channel": channel, "plan_tier": plan})

    ab_events.append({"event_id": eid2, "user_id": i, "event_type": "signed_up",
                      "event_date": signup.strftime("%Y-%m-%d"), "variant": variant})
    eid2 += 1

    activated = random.random() < act_rate
    act_dt2   = None
    if activated:
        act_dt2 = signup + timedelta(days=random.randint(0, 2))
        if act_dt2 > P2_END: act_dt2 = signup
        ab_events.append({"event_id": eid2, "user_id": i, "event_type": "activated",
                          "event_date": act_dt2.strftime("%Y-%m-%d"), "variant": variant})
        eid2 += 1

    did_ai2 = activated and random.random() < (ai_rate / act_rate)
    ai_dt2  = None
    if did_ai2:
        days_to_ai = random.randint(0, 3) if variant == "treatment" else random.randint(0, 6)
        ai_dt2 = (act_dt2 or signup) + timedelta(days=days_to_ai)
        if ai_dt2 > P2_END: ai_dt2 = act_dt2 or signup
        ab_events.append({"event_id": eid2, "user_id": i, "event_type": "first_ai_output",
                          "event_date": ai_dt2.strftime("%Y-%m-%d"), "variant": variant})
        eid2 += 1

    if did_ai2 and random.random() < w4_rate:
        ab_events.append({"event_id": eid2, "user_id": i, "event_type": "retained_week4",
                          "event_date": (signup + timedelta(days=28)).strftime("%Y-%m-%d"),
                          "variant": variant})
        eid2 += 1

    if did_ai2 and random.random() < churn_w3:
        churn_dt2 = (ai_dt2 or signup) + timedelta(days=random.randint(18, 28))
        if churn_dt2 <= P2_END:
            ab_events.append({"event_id": eid2, "user_id": i, "event_type": "churned",
                              "event_date": churn_dt2.strftime("%Y-%m-%d"), "variant": variant})
            eid2 += 1

    if activated:
        span   = max(1, (P2_END - (act_dt2 or signup)).days)
        base_n = random.randint(3, 15) if variant == "treatment" else random.randint(1, 10)
        n_sess = min(base_n, span * 2)
        for s in range(n_sess):
            sess_dt = (act_dt2 or signup) + timedelta(days=random.randint(0, min(span, 60)))
            if sess_dt > P2_END: continue
            if variant == "treatment" and s < 3:
                feat = weighted_choice(
                    ["rewrite","summarize","generate","analyze","translate","none"],
                    [0.45, 0.20, 0.15, 0.10, 0.05, 0.05])
            else:
                feat = weighted_choice(
                    ["rewrite","summarize","generate","analyze","translate","none"],
                    [0.18, 0.25, 0.28, 0.15, 0.09, 0.05])
            ab_sessions.append({
                "session_id": sid2, "user_id": i, "variant": variant,
                "session_date": sess_dt.strftime("%Y-%m-%d"),
                "session_number": s + 1, "ai_feature_used": feat,
                "duration_seconds": int(random.lognormvariate(5.4, 0.7)),
            })
            sid2 += 1

# Write Part 2 CSVs
print("  Writing Part 2 CSVs...")
write_csv(f"{DATA_DIR}/ab_users.csv",   ab_users)
write_csv(f"{DATA_DIR}/ab_events.csv",  ab_events)
write_csv(f"{DATA_DIR}/ab_sessions.csv", ab_sessions)

# Write Part 2 SQLite DB
print("  Building ab_test.db...")
db2 = sqlite3.connect(f"{DATA_DIR}/ab_test.db")
c2  = db2.cursor()
c2.executescript("""
DROP TABLE IF EXISTS ab_users; DROP TABLE IF EXISTS ab_events; DROP TABLE IF EXISTS ab_sessions;
CREATE TABLE ab_users    (user_id INT PRIMARY KEY, signup_date TEXT, variant TEXT, channel TEXT, plan_tier TEXT);
CREATE TABLE ab_events   (event_id INT PRIMARY KEY, user_id INT, event_type TEXT, event_date TEXT, variant TEXT);
CREATE TABLE ab_sessions (session_id INT PRIMARY KEY, user_id INT, variant TEXT, session_date TEXT,
                          session_number INT, ai_feature_used TEXT, duration_seconds INT);
CREATE INDEX idx_ae_user ON ab_events(user_id); CREATE INDEX idx_ae_type ON ab_events(event_type);
CREATE INDEX idx_as_user ON ab_sessions(user_id);
""")
c2.executemany("INSERT INTO ab_users VALUES (?,?,?,?,?)",
    [(u["user_id"],u["signup_date"],u["variant"],u["channel"],u["plan_tier"]) for u in ab_users])
c2.executemany("INSERT INTO ab_events VALUES (?,?,?,?,?)",
    [(e["event_id"],e["user_id"],e["event_type"],e["event_date"],e["variant"]) for e in ab_events])
c2.executemany("INSERT INTO ab_sessions VALUES (?,?,?,?,?,?,?)",
    [(s["session_id"],s["user_id"],s["variant"],s["session_date"],
      s["session_number"],s["ai_feature_used"],s["duration_seconds"]) for s in ab_sessions])
db2.commit(); db2.close()

ctrl_ids  = {u["user_id"] for u in ab_users if u["variant"] == "control"}
treat_ids = {u["user_id"] for u in ab_users if u["variant"] == "treatment"}
ctrl_ai   = sum(1 for e in ab_events if e["event_type"] == "first_ai_output" and e["user_id"] in ctrl_ids)
treat_ai  = sum(1 for e in ab_events if e["event_type"] == "first_ai_output" and e["user_id"] in treat_ids)

print(f"  Part 2 complete — {len(ab_users):,} users ({len(ctrl_ids):,} ctrl / {len(treat_ids):,} treat)")
print(f"  Control first_ai_rate  : {ctrl_ai/len(ctrl_ids):.1%}")
print(f"  Treatment first_ai_rate: {treat_ai/len(treat_ids):.1%}")
print(f"  Relative lift          : {(treat_ai/len(treat_ids))/(ctrl_ai/len(ctrl_ids))-1:.1%}")


# ══════════════════════════════════════════════════════════════════════════════
print("\n── Done ────────────────────────────────────────────────────────────────")
print(f"  All files saved to: {DATA_DIR}/")
print("  Part 1 : ai_saas.db   | users, events, sessions, subscriptions, feature_usage")
print("  Part 2 : ab_test.db   | ab_users, ab_events, ab_sessions")
