# Practical 12 Monitoring Stack

Prometheus scrapes the deployed Flask API over HTTPS. Grafana reads Prometheus and loads the dashboard from the provisioning files in this folder.

The course handout assumes FastAPI and `/docs`; this project is Flask, so its health routes are `/` and `/health`, predictions use `/predict`, and the exported metrics use `/metrics`. The deployed service listens on Render's configured port (5000 in this project). Invalid input returns HTTP 400, while an unknown route returns 404; both are counted in the 4xx alert.

## Run the checks

From this folder, start the local monitoring stack:

```powershell
docker compose up -d
```

Open Prometheus at <http://localhost:9090/targets>. The `student-result-api` target should be UP. Open Grafana at <http://localhost:3000>; its Prometheus data source and six-panel dashboard are provisioned automatically. The initial Grafana login is `admin` / `admin`; change the password in the browser and do not include it in screenshots.

Generate safe public traffic:

```powershell
Invoke-RestMethod https://student-result-prediction-hh09.onrender.com/health
Invoke-RestMethod -Method Post -Uri https://student-result-prediction-hh09.onrender.com/predict -ContentType 'application/json' -Body '{"attendance":90,"internal_marks":85,"assignment_marks":88,"previous_score":80}'
Invoke-RestMethod -Method Post -Uri https://student-result-prediction-hh09.onrender.com/predict -ContentType 'application/json' -Body '{"attendance":"invalid","internal_marks":85,"assignment_marks":88,"previous_score":80}' -SkipHttpErrorCheck
Invoke-RestMethod https://student-result-prediction-hh09.onrender.com/unknown-route -SkipHttpErrorCheck
```

The invalid prediction and missing route produce safe 4xx events, allowing `StudentAPIClientErrors` to move from inactive to pending and firing after the configured duration. `StudentAPIDown` remains a production-style availability rule.

Useful PromQL queries:

```promql
student_api_model_loaded
sum(student_api_http_requests_total)
sum(rate(student_api_http_requests_total[1m]))
sum(student_api_predictions_total{result="success"})
sum(rate(student_api_http_requests_total{status=~"4..|5.."}[5m]))
histogram_quantile(0.95, sum by (le) (rate(student_api_http_request_duration_seconds_bucket[5m])))
up{job="student-result-api"}
```

This project keeps labels to fixed route templates and status/method values. It does not put student inputs, names, identifiers, tokens, or credentials into logs or metric labels. The public `/metrics` endpoint exposes operational counters only.

Stop the local monitoring containers when finished:

```powershell
docker compose down
```
