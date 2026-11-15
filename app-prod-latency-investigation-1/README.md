# LAB-001 - Production Application Latency Investigation

## Goal

Build a small Kubernetes application with:

- 3 Checkout pods
- 2 Dependency pods
- Prometheus monitoring
- Continuous load generation

Then establish a healthy latency baseline and use the same environment for a production-style latency investigation.

---

## 1. High-Level Flow

```text
Create kind cluster
  |
  v
Build and deploy Checkout
  |
  v
Build and deploy Dependency
  |
  v
Validate Checkout -> Dependency
  |
  v
Deploy Prometheus
  |
  v
Generate continuous traffic
  |
  v
Record RPS / p50 / p95 / p99
  |
  v
Inject failure
  |
  v
Troubleshoot
  |
  v
Mitigate
  |
  v
Verify recovery
  |
  v
RCA and prevention
```

Troubleshooting memory model:

```text
Scope -> Changes -> Signals -> Dependencies -> Hypothesis -> Mitigation -> Recovery -> Prevention
```

Short form:

```text
S -> C -> S -> D -> H -> M -> R -> P
```

---

## 2. Project Structure

This guide uses the existing files in the repository. The source code and Kubernetes YAML files remain the source of truth.

```text
app-prod-latency-investigation-1/
|
|-- app/
|   |-- app.py
|   |-- checkout-app-v1.tar
|   |-- checkout-app-v2.tar
|   |-- checkout-deployment.yaml
|   |-- checkout-service.yaml
|   |-- Dockerfile
|   `-- requirements.txt
|
|-- dependency/
|   |-- dependency_app.py
|   |-- dependency-app-v1.tar
|   |-- dependency-deployment.yaml
|   |-- dependency-requirements.txt
|   |-- dependency-service.yaml
|   `-- Dockerfile-Dependency
|
|-- load-generator/
|   `-- load-generator.yaml
|
|-- observability/
|   |-- prometheus-v3.13.5.tar
|   `-- prometheus.yaml
|
|-- kind-cluster-config.yaml
`-- nginx-alpine-amd64.tar
```

For the final lab flow:

- Use `checkout-app-v2.tar`
- Use `dependency-app-v1.tar`
- Use `prometheus-v3.13.5.tar`
- `checkout-app-v1.tar` and `nginx-alpine-amd64.tar` are older/bootstrap artifacts and are not required for the final run

---

## 3. Prerequisite Check

Run from PowerShell:

```powershell
docker ps
kubectl version --client
kind version
helm version
git --version
curl.exe --version
```

Proceed only after Docker Desktop is running.

---

## 4. Create the kind Cluster

Run from the lab root:

```powershell
kind create cluster --config .\kind-cluster-config.yaml
```

Verify:

```powershell
kubectl config current-context
kubectl get nodes -o wide
kubectl get pods -A
kubectl get --raw='/readyz?verbose'
```

Expected:

```text
1 control-plane node Ready
2 worker nodes Ready
Kubernetes API ready
```

Create the application namespace:

```powershell
kubectl create namespace sre-lab
```

---

## 5. Build the Checkout Image

Go to:

```powershell
cd .\app
```

Existing files used:

```text
app.py
requirements.txt
Dockerfile
```

Build:

```powershell
docker build -t checkout-app:v2 .
```

Optional local test:

```powershell
docker run --rm -p 8080:8080 checkout-app:v2
```

From another terminal:

```powershell
curl.exe http://localhost:8080/health
curl.exe http://localhost:8080/metrics
```

Expected:

```text
/health  -> HTTP 200
/metrics -> Prometheus metrics
```

Stop the local container after validation.

---

## 6. Why We Use Local .tar Images

The kind nodes use their own containerd runtime.

During this lab, containerd hit registry TLS certificate validation errors while pulling images dynamically.

Instead of disabling TLS verification, we use this flow:

```text
Build or pull image on host
  |
  v
Save image as .tar
  |
  v
Load image directly into kind
  |
  v
Kubernetes uses the local image
```

This keeps the lab reliable even when registry access or certificate trust is a problem.

In production, images would normally be pulled from an authenticated registry such as ECR, ACR, or Artifact Registry.

---

## 7. Load Checkout Image into kind

The repository already contains:

```text
app/checkout-app-v2.tar
```

From the `app` directory:

```powershell
kind load image-archive .\checkout-app-v2.tar --name sre-lab-001
```

If the archive needs to be recreated:

```powershell
docker image save --platform linux/amd64 --output checkout-app-v2.tar checkout-app:v2
```

Verify the image is available inside the workers:

```powershell
docker exec sre-lab-001-worker crictl images | Select-String checkout
docker exec sre-lab-001-worker2 crictl images | Select-String checkout
```

---

## 8. Deploy Checkout

Use:

```text
app/checkout-deployment.yaml
app/checkout-service.yaml
```

From the `app` directory, validate first:

```powershell
kubectl apply --dry-run=server -f .\checkout-deployment.yaml
kubectl apply --dry-run=server -f .\checkout-service.yaml
```

Apply:

```powershell
kubectl apply -f .\checkout-deployment.yaml
kubectl apply -f .\checkout-service.yaml
```

Verify:

```powershell
kubectl rollout status deployment/checkout -n sre-lab
kubectl get pods -n sre-lab -o wide
kubectl get svc -n sre-lab
```

Check the Service backends:

```powershell
kubectl get endpointslice -n sre-lab -l kubernetes.io/service-name=checkout -o wide
```

Expected:

```text
3 Checkout pods Running and Ready
Checkout Service exists
EndpointSlice contains 3 Checkout pod IPs
```

Important port mapping:

```text
Checkout application :8080
Checkout Service      :80
Service targetPort    :8080
```

---

## 9. Build the Dependency Image

Go to:

```powershell
cd ..\dependency
```

Existing files used:

```text
dependency_app.py
dependency-requirements.txt
Dockerfile-Dependency
```

Build:

```powershell
docker build -f .\Dockerfile-Dependency -t dependency-app:v1 .
```

Optional local test:

```powershell
docker run --rm -p 8081:8081 dependency-app:v1
```

From another terminal:

```powershell
curl.exe http://localhost:8081/health
curl.exe http://localhost:8081/work
```

Expected:

```text
/health -> HTTP 200
/work   -> success response
```

Stop the local container after validation.

---

## 10. Load Dependency Image into kind

The repository already contains:

```text
dependency/dependency-app-v1.tar
```

From the `dependency` directory:

```powershell
kind load image-archive .\dependency-app-v1.tar --name sre-lab-001
```

If the archive needs to be recreated:

```powershell
docker image save --platform linux/amd64 --output dependency-app-v1.tar dependency-app:v1
```

---

## 11. Deploy Dependency

Use:

```text
dependency/dependency-deployment.yaml
dependency/dependency-service.yaml
```

Validate:

```powershell
kubectl apply --dry-run=server -f .\dependency-deployment.yaml
kubectl apply --dry-run=server -f .\dependency-service.yaml
```

Apply:

```powershell
kubectl apply -f .\dependency-deployment.yaml
kubectl apply -f .\dependency-service.yaml
```

Verify:

```powershell
kubectl rollout status deployment/dependency -n sre-lab
kubectl get pods -n sre-lab -o wide
```

Check Service backends:

```powershell
kubectl get endpointslice -n sre-lab -l kubernetes.io/service-name=dependency -o wide
```

Expected:

```text
2 Dependency pods Running and Ready
Dependency Service exists
EndpointSlice contains 2 Dependency pod IPs
```

---

## 12. Validate Checkout -> Dependency

Test Dependency from a Checkout pod:

```powershell
kubectl exec -n sre-lab deploy/checkout -- wget -qO- http://dependency/health
```

```powershell
kubectl exec -n sre-lab deploy/checkout -- wget -qO- http://dependency/work
```

Now test the complete request path:

```powershell
kubectl exec -n sre-lab deploy/checkout -- wget -qO- http://checkout/checkout
```

Expected:

```text
Checkout status   = success
Dependency status = success
```

Request path:

```text
Checkout Service
  |
  v
Checkout Pod
  |
  v
Dependency Service
  |
  v
Dependency Pod
```

---

## 13. Access Checkout from Windows or Bruno

Names such as:

```text
http://checkout
http://dependency
```

are Kubernetes-internal DNS names.

They work inside the cluster but not directly from Windows or Bruno.

Use port-forwarding:

```powershell
kubectl port-forward -n sre-lab svc/checkout 8080:80
```

Then access:

```text
http://localhost:8080/health
http://localhost:8080/checkout
http://localhost:8080/metrics
```

Note:

`kubectl port-forward svc/checkout` ultimately forwards to one selected backend pod. Do not use it to validate load balancing across all Checkout replicas.

---

## 14. Deploy Prometheus

Return to the lab root:

```powershell
cd ..
```

Use:

```text
observability/prometheus.yaml
observability/prometheus-v3.13.5.tar
```

Load Prometheus into kind:

```powershell
kind load image-archive .\observability\prometheus-v3.13.5.tar --name sre-lab-001
```

Validate:

```powershell
kubectl apply --dry-run=server -f .\observability\prometheus.yaml
```

Apply:

```powershell
kubectl apply -f .\observability\prometheus.yaml
```

Verify:

```powershell
kubectl get pods -n monitoring
kubectl logs -n monitoring deploy/prometheus --tail=30
```

Expected:

```text
Prometheus pod = 1/1 Running
Prometheus server ready
```

---

## 15. Access Prometheus

Run:

```powershell
kubectl port-forward -n monitoring svc/prometheus 9090:9090
```

Open:

```text
http://localhost:9090
```

Check target health in Prometheus.

Expected:

```text
Checkout   3/3 UP
Dependency 2/2 UP
Total      5/5 UP
```

PromQL:

```promql
up{job=~"checkout|dependency"}
```

Every returned target should have value:

```text
1
```

---

## 16. Deploy Continuous Load

Use:

```text
load-generator/load-generator.yaml
```

Deploy:

```powershell
kubectl apply -f .\load-generator\load-generator.yaml
```

Verify:

```powershell
kubectl get pods -n sre-lab -l app=load-generator
```

Expected:

```text
load-generator pod Running
```

The load generator continuously calls:

```text
http://checkout/checkout
```

---

## 17. Record the Healthy Baseline

### Total Checkout RPS

```promql
sum(rate(checkout_requests_total[1m]))
```

Observed healthy value:

```text
~4.04 req/s
```

### RPS by Checkout Pod

```promql
sum by (pod) (
  rate(checkout_requests_total[1m])
)
```

Expected:

```text
Traffic distributed across all 3 Checkout pods
```

### Error Rate

```promql
sum(
  rate(checkout_requests_total{status="error"}[1m])
) or vector(0)
```

Expected:

```text
~0
```

### p50

```promql
histogram_quantile(
  0.50,
  sum by (le) (
    rate(checkout_request_duration_seconds_bucket[1m])
  )
)
```

Observed:

```text
~37.5 ms
```

### p95

```promql
histogram_quantile(
  0.95,
  sum by (le) (
    rate(checkout_request_duration_seconds_bucket[1m])
  )
)
```

Observed:

```text
~48.75 ms
```

### p99

```promql
histogram_quantile(
  0.99,
  sum by (le) (
    rate(checkout_request_duration_seconds_bucket[1m])
  )
)
```

Observed:

```text
~49.75 ms
```

Healthy reference:

```text
Checkout pods       3/3 Ready
Dependency pods     2/2 Ready
Prometheus targets  5/5 UP

RPS                 ~4.04 req/s
p50                 ~37.5 ms
p95                 ~48.75 ms
p99                 ~49.75 ms
Errors              ~0%
```

---

## 18. Incident Investigation Flow

When the application becomes slow, do not immediately restart pods.

Use this order:

```text
1. Scope
2. Recent changes
3. Rate / Errors / Duration / Saturation
4. Follow the request path
5. Compare Checkout vs Dependency latency
6. Compare replicas
7. Form a hypothesis
8. Prove the hypothesis
9. Mitigate
10. Verify recovery
11. RCA and prevention
```

---

## 19. Incident Queries

### Checkout RPS

```promql
sum(rate(checkout_requests_total[1m]))
```

### Checkout status split

```promql
sum by (status) (
  rate(checkout_requests_total[1m])
)
```

### Checkout p95

```promql
histogram_quantile(
  0.95,
  sum by (le) (
    rate(checkout_request_duration_seconds_bucket[1m])
  )
)
```

### Checkout -> Dependency p95

```promql
histogram_quantile(
  0.95,
  sum by (le) (
    rate(checkout_dependency_duration_seconds_bucket[1m])
  )
)
```

### Dependency p95 by Pod

```promql
histogram_quantile(
  0.95,
  sum by (pod, le) (
    rate(dependency_request_duration_seconds_bucket[1m])
  )
)
```

### Dependency p99 by Pod

```promql
histogram_quantile(
  0.99,
  sum by (pod, le) (
    rate(dependency_request_duration_seconds_bucket[1m])
  )
)
```

### Dependency RPS by Pod

```promql
sum by (pod) (
  rate(dependency_requests_total[1m])
)
```

---

## 20. Kubernetes Commands During the Incident

Check pods and nodes:

```powershell
kubectl get pods -n sre-lab -o wide
```

Check recent events:

```powershell
kubectl get events -n sre-lab --sort-by=.lastTimestamp
```

Describe a suspicious pod:

```powershell
kubectl describe pod <pod-name> -n sre-lab
```

Logs:

```powershell
kubectl logs <pod-name> -n sre-lab
```

For a previously crashed container:

```powershell
kubectl logs <pod-name> -n sre-lab --previous
```

Check recent deployment revisions:

```powershell
kubectl rollout history deployment/checkout -n sre-lab
kubectl rollout history deployment/dependency -n sre-lab
```

Check ReplicaSets:

```powershell
kubectl get rs -n sre-lab -l app=checkout
kubectl get rs -n sre-lab -l app=dependency
```

---

## 21. Problems Already Encountered in This Lab

### A. Dependency CrashLoopBackOff

Actual issue:

```text
Gunicorn module name did not match the Python file.
```

Correct final project setup:

```text
dependency_app.py
dependency_app:app
```

Useful commands:

```powershell
kubectl describe pod <pod-name> -n sre-lab
kubectl logs <pod-name> -n sre-lab --previous
```

Lesson:

```text
CrashLoopBackOff is a symptom.
Always inspect the previous container logs and exit reason.
```

---

### B. Prometheus Checkout Targets DOWN

Symptom:

```text
PodIP:80/metrics
connection refused
```

Cause:

```text
Checkout application listens on 8080
but the Pod originally declared containerPort 80
```

Correct final setup:

```text
Container port: 8080
Service port:    80
Service target:  8080
```

Lesson:

Prometheus Pod discovery uses the declared Pod port. The Service can still work even when the declared container port is wrong.

---

### C. Registry TLS Certificate Error

Symptom:

```text
x509: certificate signed by unknown authority
```

Lab solution:

```powershell
kind load image-archive <image>.tar --name sre-lab-001
```

Do not disable TLS verification just to make the lab work.

---

### D. kind Image Digest Error

Symptom:

```text
ctr: content digest ... not found
```

Use a single-platform archive:

```powershell
docker image save --platform linux/amd64 --output image.tar image:tag
kind load image-archive .\image.tar --name sre-lab-001
```

---

### E. PowerShell and Bash Syntax

Do not use Bash `\` line continuation in PowerShell.

Prefer one-line PowerShell commands.

---

## 22. Interview Answer

> When a production application suddenly becomes slow, I first establish the blast radius and correlate the incident with recent changes. Then I check request rate, errors, latency and saturation. I follow the request path using metrics, logs and traces to determine whether latency originates in the application, Kubernetes, networking or a downstream dependency. If p50 remains normal while p95 and p99 increase sharply, I investigate partial failures such as one bad replica or dependency path. I form and test a hypothesis using evidence, mitigate safely, verify service recovery, and complete RCA and prevention actions.

---

## 23. Revision Checklist

Before considering the lab complete, be able to explain:

```text
[ ] Node Ready vs schedulable
[ ] Service port vs targetPort
[ ] Service selectors
[ ] EndpointSlices
[ ] Kubernetes DNS
[ ] Why Running does not mean healthy
[ ] CrashLoopBackOff troubleshooting
[ ] kubectl logs --previous
[ ] Why Prometheus scrapes individual pods
[ ] Counter vs histogram
[ ] p50 / p95 / p99
[ ] Tail latency
[ ] Upstream vs downstream latency
[ ] Per-pod latency comparison
[ ] Recent deployment checks
[ ] Mitigation vs permanent fix
[ ] Recovery verification
```

---

## 24. Cleanup

Delete application and monitoring namespaces:

```powershell
kubectl delete namespace sre-lab
kubectl delete namespace monitoring
```

Delete the kind cluster:

```powershell
kind delete cluster --name sre-lab-001
```

---

## 25. Current Lab Status

```text
LAB-001 - Production Application Latency Investigation

Cluster build       Complete
Checkout            Complete
Dependency          Complete
Prometheus          Complete
Load generation     Complete
Healthy baseline    Complete
Incident exercise   Continue interactively
```

Healthy reference:

```text
RPS      ~4.04 req/s
p50      ~37.5 ms
p95      ~48.75 ms
p99      ~49.75 ms
Errors   ~0%
Targets  5/5 UP
```
