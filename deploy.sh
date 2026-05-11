#!/usr/bin/env bash

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAMESPACE="custom-logging"
IMAGE_NAME="custom-app:1.0"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required"
  exit 1
fi

if ! command -v kubectl >/dev/null 2>&1; then
  echo "kubectl is required"
  exit 1
fi

echo "[1/6] Building Docker image..."
docker build -t "${IMAGE_NAME}" "${PROJECT_DIR}"

if command -v minikube >/dev/null 2>&1; then
  echo "[2/6] Loading image into Minikube..."
  minikube image load "${IMAGE_NAME}" >/dev/null 2>&1 || true
fi

if command -v kind >/dev/null 2>&1; then
  CLUSTER_NAME="$(kind get clusters 2>/dev/null | head -n 1 || true)"
  if [[ -n "${CLUSTER_NAME}" ]]; then
    echo "[2/6] Loading image into kind cluster ${CLUSTER_NAME}..."
    kind load docker-image "${IMAGE_NAME}" --name "${CLUSTER_NAME}" >/dev/null 2>&1 || true
  fi
fi

echo "[3/6] Applying namespace and configuration..."
kubectl apply -f "${PROJECT_DIR}/k8s/00-namespace.yaml"
kubectl apply -f "${PROJECT_DIR}/k8s/01-custom-app-configmap.yaml"

echo "[4/6] Creating test Pod..."
kubectl delete pod custom-app-pod-test -n "${NAMESPACE}" --ignore-not-found
kubectl apply -f "${PROJECT_DIR}/k8s/02-custom-app-pod.yaml"
kubectl wait --namespace "${NAMESPACE}" --for=condition=Ready pod/custom-app-pod-test --timeout=120s

echo "[5/6] Creating Deployment, Service, DaemonSet, StatefulSet and CronJob..."
kubectl apply -f "${PROJECT_DIR}/k8s/03-custom-app-deployment.yaml"
kubectl apply -f "${PROJECT_DIR}/k8s/04-custom-app-service.yaml"
kubectl apply -f "${PROJECT_DIR}/k8s/05-log-agent-daemonset.yaml"
kubectl apply -f "${PROJECT_DIR}/k8s/06-backup-store-statefulset.yaml"
kubectl apply -f "${PROJECT_DIR}/k8s/07-log-archive-cronjob.yaml"
kubectl rollout restart deployment/custom-app-deployment -n "${NAMESPACE}" >/dev/null 2>&1 || true

echo "[6/6] Waiting for main components..."
kubectl rollout status deployment/custom-app-deployment -n "${NAMESPACE}" --timeout=180s
kubectl rollout status daemonset/log-agent -n "${NAMESPACE}" --timeout=180s
kubectl rollout status statefulset/backup-store -n "${NAMESPACE}" --timeout=180s

echo
echo "Deployment finished."
echo "Port-forward command:"
echo "kubectl port-forward -n ${NAMESPACE} svc/custom-app-service 8080:80"
echo
echo "Useful checks:"
echo "kubectl get all -n ${NAMESPACE}"
echo "kubectl logs -n ${NAMESPACE} daemonset/log-agent"
echo "kubectl get cronjob -n ${NAMESPACE}"
