-- queries.sql
-- Part 1 (Q1-10, Q21-22): ai_saas.db
-- Part 2 (Q11-20): ab_test.db


-- Q1: funnel overview
-- note: Invited Team and Upgraded are two separate branches off First AI Output (neither requires the other)
WITH funnel_stages AS (
    SELECT
        u.user_id,
        u.channel,
        u.plan_tier,
        MAX(CASE WHEN e.event_type = 'signed_up'       THEN 1 ELSE 0 END) AS did_signup,
        MAX(CASE WHEN e.event_type = 'activated'       THEN 1 ELSE 0 END) AS did_activate,
        MAX(CASE WHEN e.event_type = 'first_ai_output' THEN 1 ELSE 0 END) AS did_first_ai,
        MAX(CASE WHEN e.event_type = 'invited_team'    THEN 1 ELSE 0 END) AS did_invite,
        MAX(CASE WHEN e.event_type = 'upgraded'        THEN 1 ELSE 0 END) AS did_upgrade
    FROM users u
    LEFT JOIN events e ON u.user_id = e.user_id
    GROUP BY u.user_id, u.channel, u.plan_tier
)
SELECT 'Signup' AS funnel_stage, COUNT(*) AS total_users, 100.0 AS conversion_pct
FROM funnel_stages WHERE did_signup = 1
UNION ALL
SELECT 'Activation', COUNT(*),
    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM funnel_stages WHERE did_signup = 1), 1)
FROM funnel_stages WHERE did_activate = 1
UNION ALL
SELECT 'First AI Output', COUNT(*),
    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM funnel_stages WHERE did_signup = 1), 1)
FROM funnel_stages WHERE did_first_ai = 1
UNION ALL
SELECT 'Team Invite', COUNT(*),
    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM funnel_stages WHERE did_signup = 1), 1)
FROM funnel_stages WHERE did_invite = 1
UNION ALL
SELECT 'Upgraded', COUNT(*),
    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM funnel_stages WHERE did_signup = 1), 1)
FROM funnel_stages WHERE did_upgrade = 1;


-- Q2: funnel by channel
WITH funnel AS (
    SELECT
        u.user_id,
        u.channel,
        MAX(CASE WHEN e.event_type = 'signed_up'       THEN 1 ELSE 0 END) AS did_signup,
        MAX(CASE WHEN e.event_type = 'first_ai_output' THEN 1 ELSE 0 END) AS did_first_ai,
        MAX(CASE WHEN e.event_type = 'upgraded'        THEN 1 ELSE 0 END) AS did_upgrade
    FROM users u
    LEFT JOIN events e ON u.user_id = e.user_id
    GROUP BY u.user_id, u.channel
)
SELECT
    channel,
    COUNT(*)                                                  AS total_signups,
    SUM(did_first_ai)                                         AS first_ai_users,
    ROUND(SUM(did_first_ai) * 100.0 / COUNT(*), 1)           AS first_ai_pct,
    SUM(did_upgrade)                                          AS upgraded_users,
    ROUND(SUM(did_upgrade) * 100.0
          / NULLIF(SUM(did_first_ai), 0), 1)                 AS upgrade_pct
FROM funnel
WHERE did_signup = 1
GROUP BY channel
ORDER BY first_ai_pct DESC;


-- Q3: cohort retention by month
-- cohort = activated users (those with >=1 session); "retained at N weeks" = last session is >= N weeks after signup
WITH cohorts AS (
    SELECT
        u.user_id,
        STRFTIME('%Y-%m', u.signup_date) AS cohort_month,
        DATE(u.signup_date)              AS signup_dt,
        MAX(DATE(s.session_date))        AS last_active_dt
    FROM users u
    JOIN sessions s ON u.user_id = s.user_id
    GROUP BY u.user_id, cohort_month, signup_dt
),
sizes AS (
    SELECT cohort_month, COUNT(DISTINCT user_id) AS sz
    FROM cohorts
    GROUP BY cohort_month
),
ret AS (
    SELECT
        c.cohort_month,
        sz.sz AS cohort_size,
        JULIANDAY(c.last_active_dt) - JULIANDAY(c.signup_dt) AS days_retained
    FROM cohorts c
    JOIN sizes sz ON c.cohort_month = sz.cohort_month
)
SELECT
    cohort_month,
    cohort_size,
    ROUND(SUM(CASE WHEN days_retained >= 7  THEN 1.0 ELSE 0 END) / cohort_size * 100, 1) AS week_1_pct,
    ROUND(SUM(CASE WHEN days_retained >= 14 THEN 1.0 ELSE 0 END) / cohort_size * 100, 1) AS week_2_pct,
    ROUND(SUM(CASE WHEN days_retained >= 28 THEN 1.0 ELSE 0 END) / cohort_size * 100, 1) AS week_4_pct,
    ROUND(SUM(CASE WHEN days_retained >= 56 THEN 1.0 ELSE 0 END) / cohort_size * 100, 1) AS week_8_pct,
    ROUND(SUM(CASE WHEN days_retained >= 84 THEN 1.0 ELSE 0 END) / cohort_size * 100, 1) AS week_12_pct
FROM ret
GROUP BY cohort_month, cohort_size
ORDER BY cohort_month;


-- Q4: retention by acquisition channel
WITH user_retention AS (
    SELECT
        u.user_id,
        u.channel,
        DATE(u.signup_date) AS signup_dt,
        JULIANDAY(MAX(DATE(s.session_date))) - JULIANDAY(DATE(u.signup_date)) AS days_retained
    FROM users u
    JOIN sessions s ON u.user_id = s.user_id
    GROUP BY u.user_id, u.channel, signup_dt
)
SELECT
    channel,
    COUNT(*)                                                           AS total_users,
    ROUND(AVG(days_retained), 1)                                       AS avg_days_retained,
    ROUND(SUM(CASE WHEN days_retained >= 56 THEN 1.0 ELSE 0 END)
          / COUNT(*) * 100, 1)                                         AS week_8_retention_pct,
    ROUND(SUM(CASE WHEN days_retained >= 84 THEN 1.0 ELSE 0 END)
          / COUNT(*) * 100, 1)                                         AS week_12_retention_pct
FROM user_retention
GROUP BY channel
ORDER BY week_8_retention_pct DESC;


-- Q5: churn risk segmentation
-- narrow feature breadth is as risky as pure inactivity
WITH user_activity AS (
    SELECT
        u.user_id,
        u.channel,
        u.plan_tier,
        MAX(DATE(s.session_date))                                          AS last_session,
        COUNT(s.session_id)                                                AS total_sessions,
        JULIANDAY('2025-12-31') - JULIANDAY(MAX(DATE(s.session_date)))     AS days_since_active,
        COUNT(DISTINCT s.ai_feature_used)                                  AS distinct_features_used,
        AVG(s.duration_seconds)                                            AS avg_session_duration
    FROM users u
    LEFT JOIN sessions s ON u.user_id = s.user_id
    WHERE u.user_id NOT IN (
        SELECT user_id FROM events WHERE event_type = 'churned'
    )
    GROUP BY u.user_id, u.channel, u.plan_tier
)
SELECT
    user_id,
    channel,
    plan_tier,
    last_session,
    total_sessions,
    ROUND(days_since_active, 0)  AS inactive_days,
    distinct_features_used,
    ROUND(avg_session_duration)  AS avg_duration_sec,
    CASE
        WHEN days_since_active > 30 AND total_sessions < 5         THEN 'High Risk'
        WHEN days_since_active > 14 AND distinct_features_used < 2 THEN 'High Risk'
        WHEN days_since_active BETWEEN 14 AND 30                   THEN 'Medium Risk'
        WHEN total_sessions < 10    AND distinct_features_used = 1 THEN 'Medium Risk'
        ELSE 'Low Risk'
    END AS churn_risk
FROM user_activity
ORDER BY inactive_days DESC;


-- Q6: feature adoption speed
WITH feature_adoption AS (
    SELECT
        fu.user_id,
        fu.feature_name,
        fu.first_used_date,
        fu.usage_count_30d,
        JULIANDAY(fu.first_used_date) - JULIANDAY(DATE(u.signup_date)) AS days_to_adopt
    FROM feature_usage fu
    JOIN users u ON fu.user_id = u.user_id
)
SELECT
    feature_name,
    COUNT(*)                        AS users_adopted,
    ROUND(AVG(days_to_adopt), 1)    AS avg_days_to_first_use,
    MIN(days_to_adopt)              AS min_days,
    MAX(days_to_adopt)              AS max_days,
    ROUND(AVG(usage_count_30d), 1)  AS avg_monthly_usage,
    MAX(usage_count_30d)            AS max_usage_30d
FROM feature_adoption
WHERE days_to_adopt >= 0
GROUP BY feature_name
ORDER BY avg_days_to_first_use;


-- Q7: feature usage vs churn rate
-- population: users who reached first_ai_output (only they can churn or adopt a feature),
-- same population as the chi-square test in analysis.py
-- (EXISTS lookups hit the user_id indexes, so this runs in about a second)
WITH flags AS (
    SELECT
        u.user_id,
        EXISTS (SELECT 1 FROM feature_usage f WHERE f.user_id = u.user_id AND f.feature_name = 'rewrite')   AS uses_rewrite,
        EXISTS (SELECT 1 FROM feature_usage f WHERE f.user_id = u.user_id AND f.feature_name = 'analyze')   AS uses_analyze,
        EXISTS (SELECT 1 FROM feature_usage f WHERE f.user_id = u.user_id AND f.feature_name = 'summarize') AS uses_summarize,
        EXISTS (SELECT 1 FROM feature_usage f WHERE f.user_id = u.user_id AND f.feature_name = 'generate')  AS uses_generate,
        EXISTS (SELECT 1 FROM feature_usage f WHERE f.user_id = u.user_id AND f.feature_name = 'translate') AS uses_translate,
        EXISTS (SELECT 1 FROM events c WHERE c.user_id = u.user_id AND c.event_type = 'churned')            AS churned
    FROM (SELECT DISTINCT user_id FROM events WHERE event_type = 'first_ai_output') u
)
SELECT
    feat AS feature_name,
    users_using_feature,
    ROUND(churned_with    * 100.0 / NULLIF(users_using_feature, 0), 1)                                  AS churn_rate_with,
    ROUND(churned_without * 100.0 / NULLIF((SELECT COUNT(*) FROM flags) - users_using_feature, 0), 1)   AS churn_rate_without
FROM (
    SELECT 'rewrite'   AS feat, SUM(uses_rewrite)    AS users_using_feature, SUM(uses_rewrite    * churned) AS churned_with, SUM((1 - uses_rewrite)    * churned) AS churned_without FROM flags
    UNION ALL
    SELECT 'analyze',           SUM(uses_analyze),              SUM(uses_analyze   * churned),    SUM((1 - uses_analyze)   * churned) FROM flags
    UNION ALL
    SELECT 'summarize',         SUM(uses_summarize),            SUM(uses_summarize * churned),    SUM((1 - uses_summarize) * churned) FROM flags
    UNION ALL
    SELECT 'generate',          SUM(uses_generate),             SUM(uses_generate  * churned),    SUM((1 - uses_generate)  * churned) FROM flags
    UNION ALL
    SELECT 'translate',         SUM(uses_translate),            SUM(uses_translate * churned),    SUM((1 - uses_translate) * churned) FROM flags
)
ORDER BY churn_rate_with;


-- Q8: MAU growth accounting (new / retained / resurrected)
WITH monthly_activity AS (
    SELECT user_id, STRFTIME('%Y-%m', session_date) AS activity_month
    FROM sessions
    GROUP BY user_id, activity_month
),
prev AS (
    SELECT
        user_id,
        activity_month,
        LAG(activity_month) OVER (PARTITION BY user_id ORDER BY activity_month) AS previous_month
    FROM monthly_activity
)
SELECT
    activity_month,
    COUNT(*) AS mau,
    SUM(CASE WHEN previous_month IS NULL THEN 1 ELSE 0 END) AS new_users,
    SUM(CASE WHEN previous_month = STRFTIME('%Y-%m', DATE(activity_month || '-01', '-1 month'))
             THEN 1 ELSE 0 END) AS retained_users,
    SUM(CASE WHEN previous_month IS NOT NULL
             AND previous_month != STRFTIME('%Y-%m', DATE(activity_month || '-01', '-1 month'))
             THEN 1 ELSE 0 END) AS resurrected_users
FROM prev
GROUP BY activity_month
ORDER BY activity_month;


-- Q9: MRR by plan per month
WITH active_subs AS (
    SELECT
        user_id,
        plan,
        mrr_inr,
        start_date,
        COALESCE(NULLIF(end_date, ''), '2099-01-01') AS active_until
    FROM subscriptions
    WHERE plan != 'free'
),
months AS MATERIALIZED (
    SELECT DISTINCT STRFTIME('%Y-%m', session_date) AS revenue_month
    FROM sessions
)
SELECT
    m.revenue_month,
    SUM(CASE WHEN a.plan = 'pro'        THEN a.mrr_inr ELSE 0 END) AS pro_mrr,
    SUM(CASE WHEN a.plan = 'enterprise' THEN a.mrr_inr ELSE 0 END) AS enterprise_mrr,
    SUM(a.mrr_inr)                                                   AS total_mrr,
    COUNT(DISTINCT a.user_id)                                        AS paying_customers
FROM months m
JOIN active_subs a
    ON m.revenue_month >= STRFTIME('%Y-%m', a.start_date)
   AND m.revenue_month <  STRFTIME('%Y-%m', a.active_until)
GROUP BY m.revenue_month
ORDER BY m.revenue_month;


-- Q10: churn timing — when do users leave after first AI output
WITH first_ai AS (
    SELECT user_id, MIN(event_date) AS first_ai_date
    FROM events
    WHERE event_type = 'first_ai_output'
    GROUP BY user_id
),
churn AS (
    SELECT user_id, MIN(event_date) AS churn_date
    FROM events
    WHERE event_type = 'churned'
    GROUP BY user_id
),
timing AS (
    SELECT
        c.user_id,
        JULIANDAY(c.churn_date) - JULIANDAY(f.first_ai_date) AS days_to_churn
    FROM churn c
    JOIN first_ai f ON c.user_id = f.user_id
    WHERE JULIANDAY(c.churn_date) >= JULIANDAY(f.first_ai_date)
)
SELECT
    CASE
        WHEN days_to_churn <  7 THEN 'Week 1'
        WHEN days_to_churn < 14 THEN 'Week 2'
        WHEN days_to_churn < 21 THEN 'Week 3'
        WHEN days_to_churn < 28 THEN 'Week 4'
        WHEN days_to_churn < 60 THEN 'Month 2'
        WHEN days_to_churn < 90 THEN 'Month 3'
        ELSE 'Month 3+'
    END AS churn_period,
    COUNT(*) AS churned_users,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) AS churn_pct
FROM timing
GROUP BY churn_period
ORDER BY MIN(days_to_churn);


-- -------------------------------------------------------
-- ab_test.db from here
-- -------------------------------------------------------


-- Q11: experiment health check — run this before anything else
SELECT
    variant,
    COUNT(*)                                          AS total_users,
    MIN(signup_date)                                  AS first_signup,
    MAX(signup_date)                                  AS last_signup,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) AS pct_of_total
FROM ab_users
GROUP BY variant;


-- Q12: channel split across variants — check for imbalance
SELECT
    channel,
    SUM(CASE WHEN variant = 'control'   THEN 1 ELSE 0 END) AS ctrl_users,
    SUM(CASE WHEN variant = 'treatment' THEN 1 ELSE 0 END) AS treat_users,
    ROUND(SUM(CASE WHEN variant = 'control'   THEN 1.0 ELSE 0 END) / COUNT(*) * 100, 1) AS ctrl_pct,
    ROUND(SUM(CASE WHEN variant = 'treatment' THEN 1.0 ELSE 0 END) / COUNT(*) * 100, 1) AS treat_pct
FROM ab_users
GROUP BY channel
ORDER BY channel;


-- Q13: primary metric — first AI output rate per variant
WITH signups AS (
    SELECT variant, COUNT(DISTINCT user_id) AS n_users
    FROM ab_users
    GROUP BY variant
),
conversions AS (
    SELECT variant, COUNT(DISTINCT user_id) AS converted
    FROM ab_events
    WHERE event_type = 'first_ai_output'
    GROUP BY variant
)
SELECT
    s.variant,
    s.n_users,
    COALESCE(c.converted, 0) AS converted,
    ROUND(COALESCE(c.converted, 0) * 100.0 / s.n_users, 2) AS conversion_rate_pct,
    ROUND(
        (COALESCE(c.converted, 0) * 1.0 / s.n_users)
        - LAG(COALESCE(c.converted, 0) * 1.0 / s.n_users)
          OVER (ORDER BY s.variant ASC)
    , 4) AS absolute_lift
FROM signups s
LEFT JOIN conversions c ON s.variant = c.variant
ORDER BY s.variant;


-- Q14: time to first AI output per variant
WITH signups AS (
    SELECT user_id, variant, DATE(signup_date) AS signup_dt
    FROM ab_users
),
ai_events AS (
    SELECT user_id, DATE(event_date) AS ai_date
    FROM ab_events
    WHERE event_type = 'first_ai_output'
)
SELECT
    s.variant,
    COUNT(a.user_id)                                                              AS converted_users,
    ROUND(AVG(JULIANDAY(a.ai_date) - JULIANDAY(s.signup_dt)), 2)                  AS avg_days_to_convert,
    MIN(JULIANDAY(a.ai_date) - JULIANDAY(s.signup_dt))                            AS min_days,
    MAX(JULIANDAY(a.ai_date) - JULIANDAY(s.signup_dt))                            AS max_days,
    SUM(CASE WHEN JULIANDAY(a.ai_date) - JULIANDAY(s.signup_dt) <= 1 THEN 1 ELSE 0 END) AS same_or_next_day,
    SUM(CASE WHEN JULIANDAY(a.ai_date) - JULIANDAY(s.signup_dt) <= 3 THEN 1 ELSE 0 END) AS within_3_days,
    SUM(CASE WHEN JULIANDAY(a.ai_date) - JULIANDAY(s.signup_dt) <= 7 THEN 1 ELSE 0 END) AS within_7_days
FROM signups s
JOIN ai_events a ON s.user_id = a.user_id
GROUP BY s.variant;


-- Q15: week-4 retention per variant
SELECT
    u.variant,
    COUNT(DISTINCT u.user_id)                                    AS total_users,
    COUNT(DISTINCT e.user_id)                                    AS retained_w4,
    ROUND(COUNT(DISTINCT e.user_id) * 100.0
          / COUNT(DISTINCT u.user_id), 2)                        AS w4_retention_pct
FROM ab_users u
LEFT JOIN ab_events e
    ON u.user_id = e.user_id
   AND e.event_type = 'retained_week4'
GROUP BY u.variant;


-- Q16: week-1 session depth per variant
-- sessions in the first 7 days after signup, per assigned user (users with no session count as 0)
WITH w1 AS (
    SELECT u.user_id, u.variant, COUNT(s.session_id) AS w1_sessions
    FROM ab_users u
    LEFT JOIN ab_sessions s
        ON u.user_id = s.user_id
       AND JULIANDAY(s.session_date) - JULIANDAY(u.signup_date) < 7
    GROUP BY u.user_id, u.variant
)
SELECT
    variant,
    COUNT(*)                          AS users,
    ROUND(AVG(w1_sessions), 2)        AS avg_w1_sessions,
    SUM(CASE WHEN w1_sessions > 0 THEN 1 ELSE 0 END) AS users_with_w1_session
FROM w1
GROUP BY variant;


-- Q17: feature usage shift between variants
SELECT
    u.variant,
    s.ai_feature_used,
    COUNT(*) AS session_count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (PARTITION BY u.variant), 1) AS pct_of_sessions
FROM ab_sessions s
JOIN ab_users u ON s.user_id = u.user_id
WHERE s.ai_feature_used != 'none'
GROUP BY u.variant, s.ai_feature_used
ORDER BY u.variant, pct_of_sessions DESC;


-- Q18: cumulative conversion curve by day (novelty effect check)
WITH user_signup AS (
    SELECT user_id, variant, DATE(signup_date) AS signup_dt
    FROM ab_users
),
user_ai AS (
    SELECT user_id, DATE(event_date) AS ai_dt
    FROM ab_events
    WHERE event_type = 'first_ai_output'
),
days_to_convert AS (
    SELECT
        us.variant,
        CAST(JULIANDAY(ua.ai_dt) - JULIANDAY(us.signup_dt) AS INT) AS day_num
    FROM user_signup us
    JOIN user_ai ua ON us.user_id = ua.user_id
    WHERE JULIANDAY(ua.ai_dt) - JULIANDAY(us.signup_dt) BETWEEN 0 AND 14
),
totals AS (
    SELECT variant, COUNT(*) AS n_total
    FROM ab_users
    GROUP BY variant
)
SELECT
    d.variant,
    d.day_num,
    COUNT(*) AS converted_on_day,
    SUM(COUNT(*)) OVER (PARTITION BY d.variant ORDER BY d.day_num) AS cumulative_converted,
    ROUND(SUM(COUNT(*)) OVER (PARTITION BY d.variant ORDER BY d.day_num)
          * 100.0 / t.n_total, 2) AS cumulative_rate_pct
FROM days_to_convert d
JOIN totals t ON d.variant = t.variant
GROUP BY d.variant, d.day_num
ORDER BY d.variant, d.day_num;


-- Q19: channel x variant subgroup — does lift hold across channels
WITH base AS (
    SELECT
        u.user_id,
        u.variant,
        u.channel,
        MAX(CASE WHEN e.event_type = 'first_ai_output' THEN 1 ELSE 0 END) AS converted
    FROM ab_users u
    LEFT JOIN ab_events e ON u.user_id = e.user_id
    GROUP BY u.user_id, u.variant, u.channel
)
SELECT
    channel,
    ROUND(SUM(CASE WHEN variant = 'control'   THEN converted ELSE 0 END) * 100.0
          / NULLIF(SUM(CASE WHEN variant = 'control'   THEN 1 ELSE 0 END), 0), 1) AS ctrl_rate,
    ROUND(SUM(CASE WHEN variant = 'treatment' THEN converted ELSE 0 END) * 100.0
          / NULLIF(SUM(CASE WHEN variant = 'treatment' THEN 1 ELSE 0 END), 0), 1) AS treat_rate,
    SUM(CASE WHEN variant = 'control'   THEN 1 ELSE 0 END) AS ctrl_n,
    SUM(CASE WHEN variant = 'treatment' THEN 1 ELSE 0 END) AS treat_n
FROM base
GROUP BY channel
ORDER BY treat_rate DESC;


-- Q20: plan tier x variant — does lift hold across free and paid
WITH base AS (
    SELECT
        u.user_id,
        u.variant,
        u.plan_tier,
        MAX(CASE WHEN e.event_type = 'first_ai_output' THEN 1 ELSE 0 END) AS converted
    FROM ab_users u
    LEFT JOIN ab_events e ON u.user_id = e.user_id
    GROUP BY u.user_id, u.variant, u.plan_tier
)
SELECT
    plan_tier,
    ROUND(SUM(CASE WHEN variant = 'control'   THEN converted ELSE 0 END) * 100.0
          / NULLIF(SUM(CASE WHEN variant = 'control'   THEN 1 ELSE 0 END), 0), 1) AS ctrl_rate,
    ROUND(SUM(CASE WHEN variant = 'treatment' THEN converted ELSE 0 END) * 100.0
          / NULLIF(SUM(CASE WHEN variant = 'treatment' THEN 1 ELSE 0 END), 0), 1) AS treat_rate,
    SUM(CASE WHEN variant = 'control'   THEN 1 ELSE 0 END) AS ctrl_n,
    SUM(CASE WHEN variant = 'treatment' THEN 1 ELSE 0 END) AS treat_n
FROM base
GROUP BY plan_tier
ORDER BY plan_tier;


-- Q21: feature usage vs churn — significance test inputs (population restricted to
-- users who reached first_ai_output, since only they are eligible to churn or
-- adopt a feature; run the contingency counts below through a chi-square test)
WITH base AS (
    SELECT
        u.user_id,
        EXISTS (SELECT 1 FROM feature_usage f WHERE f.user_id = u.user_id AND f.feature_name = 'rewrite') AS uses_rewrite,
        EXISTS (SELECT 1 FROM events c WHERE c.user_id = u.user_id AND c.event_type = 'churned')          AS churned
    FROM (SELECT DISTINCT user_id FROM events WHERE event_type = 'first_ai_output') u
)
SELECT
    uses_rewrite,
    COUNT(*) AS total_users,
    SUM(churned) AS churned_users,
    ROUND(SUM(churned) * 100.0 / COUNT(*), 2) AS churn_rate_pct
FROM base
GROUP BY uses_rewrite;


-- Q22: churn-ROI — revenue impact of closing the rewrite-adoption churn gap
-- (paying users who reached first_ai_output only — the eligible population)
-- "churn" here = subscription status 'cancelled'
WITH paying AS (
    SELECT s.user_id, s.mrr_inr, s.status,
        EXISTS (SELECT 1 FROM feature_usage f WHERE f.user_id = s.user_id AND f.feature_name = 'rewrite') AS uses_rewrite
    FROM subscriptions s
    WHERE s.plan != 'free'
      AND EXISTS (SELECT 1 FROM events e WHERE e.user_id = s.user_id AND e.event_type = 'first_ai_output')
)
SELECT
    CASE WHEN uses_rewrite = 1 THEN 'uses_rewrite' ELSE 'no_rewrite' END AS segment,
    COUNT(*) AS total_paying,
    SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled,
    ROUND(SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS churn_pct,
    SUM(CASE WHEN status = 'cancelled' THEN mrr_inr ELSE 0 END) AS mrr_lost,
    ROUND(AVG(mrr_inr), 0) AS avg_mrr
FROM paying
GROUP BY segment;
