# Power BI — AI SaaS Growth Intelligence

All data is simulated (`data_generator.py`). After building or refreshing the report, check it against the **Expected values** table at the bottom. If a card doesn't match, the model or a measure is wrong.

Import all 8 CSVs via Get Data → Text/CSV:
`users.csv, events.csv, sessions.csv, subscriptions.csv, feature_usage.csv, ab_users.csv, ab_events.csv, ab_sessions.csv`

---

## Relationships

Part 1 tables — connect everything to users on user_id (1:Many):
- users → events
- users → sessions
- users → subscriptions
- users → feature_usage

Part 2 tables — connect to ab_users on user_id (1:Many):
- ab_users → ab_events
- ab_users → ab_sessions

---

## Calculated columns (users table)

```dax
Signup Month = FORMAT(users[signup_date], "YYYY-MM")

Days Since Signup = DATEDIFF(users[signup_date], TODAY(), DAY)

Cohort Label = FORMAT(users[signup_date], "MMM YYYY")
```

---

## DAX Measures

Create a blank table called _Measures and put everything here.

```dax
Total Users = DISTINCTCOUNT(users[user_id])

Total Sessions = COUNTROWS(sessions)

Paying Users =
CALCULATE(
    DISTINCTCOUNT(subscriptions[user_id]),
    subscriptions[plan] <> "free",
    subscriptions[status] = "active"
)

Activated Users =
CALCULATE(
    DISTINCTCOUNT(events[user_id]),
    events[event_type] = "activated"
)

First AI Output Users =
CALCULATE(
    DISTINCTCOUNT(events[user_id]),
    events[event_type] = "first_ai_output"
)

Activation Rate = DIVIDE([Activated Users], [Total Users], 0)

First AI Rate = DIVIDE([First AI Output Users], [Total Users], 0)

Upgrade Count =
CALCULATE(
    DISTINCTCOUNT(events[user_id]),
    events[event_type] = "upgraded"
)

-- Invite and Upgrade are separate branches off First AI Output, so both are measured against it
Invited Team Users =
CALCULATE(
    DISTINCTCOUNT(events[user_id]),
    events[event_type] = "invited_team"
)

Invite Rate = DIVIDE([Invited Team Users], [First AI Output Users], 0)

Upgrade Rate = DIVIDE([Upgrade Count], [First AI Output Users], 0)

Churned Users =
CALCULATE(
    DISTINCTCOUNT(events[user_id]),
    events[event_type] = "churned"
)

-- Churn can only happen after first AI output, so the meaningful churn rate uses that population
Churn Rate = DIVIDE([Churned Users], [First AI Output Users], 0)

Churn Rate (all signups) = DIVIDE([Churned Users], [Total Users], 0)

Active Users = [Total Users] - [Churned Users]

Retention Rate = 1 - [Churn Rate (all signups)]

Avg Session Duration Min =
DIVIDE(SUM(sessions[duration_seconds]), COUNTROWS(sessions), 0) / 60

Avg Sessions Per User = DIVIDE([Total Sessions], [Total Users], 0)

Total MRR =
CALCULATE(
    SUM(subscriptions[mrr_inr]),
    subscriptions[status] = "active",
    subscriptions[plan] <> "free"
)

Pro MRR =
CALCULATE(
    SUM(subscriptions[mrr_inr]),
    subscriptions[plan] = "pro",
    subscriptions[status] = "active"
)

Enterprise MRR =
CALCULATE(
    SUM(subscriptions[mrr_inr]),
    subscriptions[plan] = "enterprise",
    subscriptions[status] = "active"
)

ARPU = DIVIDE([Total MRR], [Paying Users], 0)

Rewrite Users =
CALCULATE(
    DISTINCTCOUNT(feature_usage[user_id]),
    feature_usage[feature_name] = "rewrite"
)

Rewrite Adoption Rate = DIVIDE([Rewrite Users], [First AI Output Users], 0)

Avg Feature Usage 30d = AVERAGE(feature_usage[usage_count_30d])

Features Per User = DIVIDE(COUNTROWS(feature_usage), [First AI Output Users], 0)

Organic Users =
CALCULATE(DISTINCTCOUNT(users[user_id]), users[channel] = "organic_search")

Paid Users =
CALCULATE(
    DISTINCTCOUNT(users[user_id]),
    users[channel] IN {"paid_google", "paid_meta"}
)

Organic Paid Ratio = DIVIDE([Organic Users], [Paid Users], 0)

AB Control Users =
CALCULATE(DISTINCTCOUNT(ab_users[user_id]), ab_users[variant] = "control")

AB Treatment Users =
CALCULATE(DISTINCTCOUNT(ab_users[user_id]), ab_users[variant] = "treatment")

AB Control Rate =
DIVIDE(
    CALCULATE(
        DISTINCTCOUNT(ab_events[user_id]),
        ab_events[event_type] = "first_ai_output",
        ab_events[variant] = "control"
    ),
    [AB Control Users], 0
)

AB Treatment Rate =
DIVIDE(
    CALCULATE(
        DISTINCTCOUNT(ab_events[user_id]),
        ab_events[event_type] = "first_ai_output",
        ab_events[variant] = "treatment"
    ),
    [AB Treatment Users], 0
)

AB Absolute Lift = [AB Treatment Rate] - [AB Control Rate]

AB Relative Lift = DIVIDE([AB Absolute Lift], [AB Control Rate], 0)

AB Control W4 Retention =
DIVIDE(
    CALCULATE(
        DISTINCTCOUNT(ab_events[user_id]),
        ab_events[event_type] = "retained_week4",
        ab_events[variant] = "control"
    ),
    [AB Control Users], 0
)

AB Week1 Sessions Per User =
-- sessions in the first 7 days after signup, averaged over all assigned users
DIVIDE(
    CALCULATE(
        COUNTROWS(ab_sessions),
        FILTER(ab_sessions,
            DATEDIFF(RELATED(ab_users[signup_date]), ab_sessions[session_date], DAY) < 7)),
    DISTINCTCOUNT(ab_users[user_id]), 0)

AB Treatment W4 Retention =
DIVIDE(
    CALCULATE(
        DISTINCTCOUNT(ab_events[user_id]),
        ab_events[event_type] = "retained_week4",
        ab_events[variant] = "treatment"
    ),
    [AB Treatment Users], 0
)
```

---

## Cohort retention table (New Table)

Cohort = activated users (users with at least one session), the same definition as Q3 in `queries.sql`. "Retained at week N" means the user has a session at least N×7 days after signup.

```dax
CohortRetention =
ADDCOLUMNS(
    SUMMARIZE(users, users[Signup Month]),
    "Cohort Size", CALCULATE(DISTINCTCOUNT(sessions[user_id])),
    "Wk1 Retained",
        CALCULATE(
            DISTINCTCOUNT(sessions[user_id]),
            FILTER(sessions,
                DATEDIFF(RELATED(users[signup_date]), sessions[session_date], DAY) >= 7)),
    "Wk4 Retained",
        CALCULATE(
            DISTINCTCOUNT(sessions[user_id]),
            FILTER(sessions,
                DATEDIFF(RELATED(users[signup_date]), sessions[session_date], DAY) >= 28)),
    "Wk8 Retained",
        CALCULATE(
            DISTINCTCOUNT(sessions[user_id]),
            FILTER(sessions,
                DATEDIFF(RELATED(users[signup_date]), sessions[session_date], DAY) >= 56))
)
```

Then add three calculated columns to this table: `Wk1 % = DIVIDE([Wk1 Retained], [Cohort Size])`, and the same for Wk4 and Wk8. Exclude cohorts after 2025-09 (they have less than 56 days of history).

---

## Dashboard pages

**Page 1 — Executive Overview**
KPI cards: Total Users, Activation Rate, First AI Rate, Churn Rate, Total MRR. Line chart of MAU by month. Donut for plan tier split. Bar for users by channel. Slicers on plan_tier, channel, signup_date range. Churn Rate here is churn among first-AI users (34.9%), so use a neutral colour or compare it against a target you choose; the thresholds in earlier drafts (red above 15%) would flag every period red.

**Page 2 — Funnel**
Built-in funnel visual: signed_up → activated → first_ai_output → invited_team → upgraded. Clustered bar for first AI rate by channel. Table with channel, signups, first AI rate, invite rate, upgrade rate. Show Invited Team and Upgraded as two branches off First AI Output (the built-in funnel visual draws them as a sequence). Slicer on plan_tier.

**Page 3 — Cohort Retention**
Matrix visual with cohort month as rows and Wk1/Wk4/Wk8 as columns. Background colour rule from red (0%) to green (100%). Line chart showing retention curve per channel. Slicer on channel.

**Page 4 — Feature Adoption**
Clustered bar of avg usage_count_30d by feature. Stacked bar of feature distribution as % of users. Scatter of features per user vs session count (skip it if you can't explain what it shows; the chi-square bars matter more). KPI card for Rewrite Adoption Rate. Slicer on plan_tier.

**Page 5 — A/B Test**
KPI cards: AB Control Rate, AB Treatment Rate, AB Absolute Lift, AB Relative Lift. Clustered bar of control vs treatment for first AI output rate. Clustered bar of control vs treatment for week-4 retention. Table with channel × variant breakdown. Slicers on ab_users channel and plan_tier. Colour AB Relative Lift green above 10%, amber 5–10%, red below 5%.

---

## Formatting

Background `#1A1A2E`, card background `#16213E`, accent `#FF6B35`, font Segoe UI, titles 14pt, KPI values 28pt, grid lines off.

---

## Export checklist

- Export all 5 pages as PNG
- Save .pbix to project folder
- Screenshot the model view for README

---

## Expected values (check your report against these)

| Measure | Expected |
|---|---|
| Total Users | 30,000 |
| Activated Users / Activation Rate | 23,918 / 79.7% |
| First AI Output Users / First AI Rate | 18,033 / 60.1% |
| Invited Team Users / Invite Rate | 3,667 / 20.3% |
| Upgrade Count / Upgrade Rate | 1,740 / 9.6% |
| Churned Users / Churn Rate (first-AI users) | 6,294 / 34.9% |
| Churn Rate (all signups) | 21.0% |
| Total Sessions | 175,151 |
| Rewrite Adoption Rate | 47.2% |
| AB Control Rate / AB Treatment Rate | 34.7% / 49.9% |
| AB Relative Lift | +43.7% |
| AB Control / Treatment W4 Retention | 15.8% / 26.1% |
| AB Week1 Sessions Per User (control / treatment) | 0.68 / 1.09 |
