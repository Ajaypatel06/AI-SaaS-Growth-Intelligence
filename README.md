# AI SaaS Growth Intelligence

I wanted to practise product analytics end to end: find where an AI writing app loses its users, then test a fix. Part 1 is the diagnosis (SQL, Python, stats). Part 2 is an A/B test of one change to onboarding.

Ajay Patel · Mumbai · [github.com/Ajaypatel06](https://github.com/Ajaypatel06)

**The data is simulated.** I generated it with `data_generator.py` (30,000 users for Part 1, 6,200 for Part 2, fixed seed). It is not from a real company. I also built some effects into the generator myself, like Rewrite lowering churn and the A/B treatment helping. So the results show the analysis works, not that a real product behaves this way. I say more about this under Limitations.

Run `data_generator.py` and then `analysis.py` and you will get the same numbers as below.

## What I was asking

Where do users drop off, which channels and features go with users staying, and does changing onboarding actually move the numbers?

## What I found

**Most users are lost early.** 39.9% of signups (11,967 of 30,000) never get their first AI output. Of the ones who do, 20.3% invite a teammate and 9.6% upgrade. Those two are separate paths from first output, so I measured each against first-output users, not against each other.

| Signed up | Activated | First AI output | Invited team | Upgraded |
|---|---|---|---|---|
| 30,000 | 23,918 (79.7%) | 18,033 (60.1%) | 3,667 | 1,740 |

**Churn.** 34.9% of users who reach first output later churn (6,294 users). The busiest window is 21 to 27 days after first output: 2,248 users, 35.7% of all churn. Days 14 to 20 have another 18%, so a nudge around day 14 would land just before the peak.

**Features.** I ran a chi-square test on feature use vs churn, only on users who reached first output (the only ones who can churn).

| Feature | Churn with | Churn without | p-value |
|---|---|---|---|
| Rewrite | 28.3% | 40.8% | < 0.001 |
| Analyze | 32.4% | 37.1% | < 0.001 |
| Summarize | 34.5% | 35.3% | 0.28 |
| Generate | 34.3% | 35.4% | 0.12 |
| Translate | 34.6% | 35.1% | 0.51 |

Only Rewrite and Analyze show a real difference. The other three don't, and I'm keeping them in the table so I don't oversell the result.

**Channels.**

| Channel | First-output rate | Week-8 retention |
|---|---|---|
| Organic Search | 71.3% | 61.7% |
| Referral | 68.8% | 55.8% |
| Direct | 61.2% | 49.4% |
| Paid Google | 52.1% | 36.5% |
| Paid Meta | 41.3% | 29.3% |

Organic keeps users about 2.1x better than Paid Meta at week 8. "Retained" here means the last session is at least 56 days after signup. This is only retention, so it can't tell you where to put ad budget. That needs CAC and LTV, which I don't have.

**Churn model.** Logistic regression, 11 features, 80/20 split, ROC-AUC 0.63. That is weak, so I'd use it to understand churn, not to predict it. My first version scored 0.75, but I had included users who never reached first output and so could never churn. Once I removed them, the score dropped and the "more features means more churn" pattern disappeared. I left this in the README on purpose.

**Revenue.** Among paying users who reached first output, 28.8% of non-Rewrite users cancelled vs 18.9% of Rewrite users. If that gap closed, about 473 subscriptions are kept, roughly Rs 8.4 lakh a month (about Rs 1 crore a year). This assumes Rewrite is the cause, which is exactly what Part 2 tries to test.

## A/B test

6,200 users, 3,100 per group, March to September 2025. Control got the normal onboarding, treatment got a flow that starts with Rewrite.

| Metric | Control | Treatment | Change | Test |
|---|---|---|---|---|
| First AI output rate | 34.7% | 49.9% | +15.2 pp (+43.7%) | z-test, p < 0.001 |
| Week-4 retention | 15.8% | 26.1% | +10.3 pp (+65%) | chi-square, p < 0.001 |
| Sessions in first 7 days | 0.68 | 1.09 | +60% | Mann-Whitney, p < 0.001 |

The lift shows up in all five channels. Each channel only has 300 to 900 users per group, so I wouldn't read anything into which one is "best".

## What I'd recommend

1. Ship the Rewrite-first onboarding.
2. Add an in-app check-in around day 14.
3. Treat the 40% who never reach first output as the biggest leak, and invite/upgrade as the money problem.
4. Compare Paid Meta against organic using CAC and LTV before moving budget.
5. Don't use the churn scores for outreach yet. AUC 0.63 is too weak.

## Limitations

- The data is simulated and I wrote the Rewrite and A/B effects into the generator. The test finds what I put in. What this project proves is the method.
- Groups are assigned by user_id odd/even, a shortcut for real randomisation.
- The generator doesn't model novelty effects, so "no novelty spike" is not strong evidence.
- Week-8 retention includes late-2025 signups who haven't had 56 days yet.
- The churn model uses behaviour over a user's whole life, so it explains churn after the fact.

## How I built it

[Write 3 to 5 sentences here in your own words: why you picked this topic, what was hardest, one thing you got wrong and fixed, what you'd do next. Only write what is true.]

## Files

```
data_generator.py     simulates the data
analysis.py           charts, tests, churn model, revenue estimate, A/B stats
build_dashboard.py    rebuilds dashboard.html from the databases
queries.sql           22 queries (Q1-10, Q21-22 on ai_saas.db; Q11-20 on ab_test.db)
dashboard.html        5-page dashboard, open in a browser
powerbi_guide.md      DAX measures and report layout
data/  charts/  assets/  powerbi/
```

## Run it

```bash
pip install pandas numpy matplotlib seaborn scikit-learn scipy
python data_generator.py
python analysis.py
python build_dashboard.py
```

Stack: Python, SQL (SQLite), Power BI and DAX, scikit-learn, SciPy, Chart.js.
