# Distributed Logging Homework

## Что входит в проект

- Простое пользовательское API на Python без внешних зависимостей
- Dockerfile для сборки образа `custom-app:1.0`
- Kubernetes-манифесты для `ConfigMap`, тестового `Pod`, `Deployment`, `Service`, `DaemonSet`, `StatefulSet` и `CronJob`
- Скрипт `deploy.sh` для автоматического развёртывания

## Структура

- `src/app.py` — приложение с REST API
- `k8s/00-namespace.yaml` — namespace
- `k8s/01-custom-app-configmap.yaml` — настройки приложения
- `k8s/02-custom-app-pod.yaml` — отдельный Pod для начальной проверки
- `k8s/03-custom-app-deployment.yaml` — Deployment на 3 реплики
- `k8s/04-custom-app-service.yaml` — ClusterIP Service
- `k8s/05-log-agent-daemonset.yaml` — DaemonSet для чтения логов с узлов
- `k8s/06-backup-store-statefulset.yaml` — StatefulSet для отдельного хранилища
- `k8s/07-log-archive-cronjob.yaml` — CronJob для архивирования логов раз в 10 минут
- `k8s/08-istio-gateway.yaml` — Istio Gateway для HTTP-трафика на порту 80
- `k8s/09-istio-virtualservice.yaml` — внешние маршруты, fallback 404 и политика для `POST /log`
- `k8s/10-istio-destinationrule.yaml` — балансировка, connection pool и mTLS для сервиса приложения
- `deploy.sh` — общий скрипт развёртывания

## REST API

- `GET /` — возвращает строку `Welcome to the custom app`
- `GET /status` — возвращает JSON `{"status": "ok"}`
- `POST /log` — принимает JSON `{"message": "some log"}` и пишет запись в `/app/logs/app.log`
- `GET /logs` — возвращает содержимое `/app/logs/app.log`

Приложение читает настройки из `ConfigMap`, смонтированного в `/app/config`.
Файлы `welcome_message`, `welcome_header` и `log_level` перечитываются на каждом запросе, поэтому их изменение применяется автоматически без пересоздания Pod.
Параметр `server_port` тоже хранится в `ConfigMap`, но используется при старте процесса, поэтому его обычно меняют вместе с пересозданием Pod или Deployment.

## Запуск

Запуск из терминала:

```bash
chmod +x deploy.sh
./deploy.sh
```

Скрипт рассчитан на локальный кластер `Minikube` или `kind`: он собирает Docker-образ и при наличии этих инструментов загружает его в кластер автоматически.
Перед развёртыванием приложения скрипт устанавливает Istio через `istioctl install --set profile=demo -y`, включает sidecar injection для namespace `custom-logging` и применяет Istio-манифесты.

## Проверка работы

После развёртывания выполнить:

```bash
kubectl port-forward -n istio-system svc/istio-ingressgateway 8080:80
```

И в другом терминале:

```bash
curl http://127.0.0.1:8080/
curl http://127.0.0.1:8080/status
curl -X POST http://127.0.0.1:8080/log \
  -H "Content-Type: application/json" \
  -d '{"message": "test"}'
curl -i http://127.0.0.1:8080/logs
curl -i http://127.0.0.1:8080/wrong
```

Для проверки балансировки удобно смотреть заголовок `X-Pod-Name`.
Так как у каждой реплики свой `emptyDir`, файл логов хранится отдельно в каждом Pod.
Маршрут `POST /log` через Istio Gateway получает искусственную задержку 2 секунды, timeout 1 секунду и до 2 retry-попыток, поэтому внешний запрос должен завершаться ошибкой по timeout.

## Проверка DaemonSet и CronJob

Проверить агента логов:

```bash
kubectl apply -f k8s/05-log-agent-daemonset.yaml
kubectl rollout status daemonset/log-agent -n custom-logging

curl -X POST http://127.0.0.1:8080/log \
  -H "Content-Type: application/json" \
  -d '{"message": "log for daemonset check"}'

kubectl logs -n custom-logging daemonset/log-agent
```

В этой реализации `DaemonSet` читает `app.log` напрямую из `emptyDir` томов Pod через путь `/var/lib/kubelet/pods/.../volumes/kubernetes.io~empty-dir/app-logs/app.log`.

Запустить архивирование вручную:

```bash
kubectl create job --from=cronjob/app-log-archive manual-archive -n custom-logging
kubectl get jobs -n custom-logging
kubectl logs job/manual-archive -n custom-logging
```

## Изменение ConfigMap

Изменить значения в файле `k8s/01-custom-app-configmap.yaml`, затем применить:

```bash
kubectl apply -f k8s/01-custom-app-configmap.yaml
```

Через короткое время Kubernetes обновит смонтированные файлы в контейнерах, и приложение начнёт использовать новые значения.

Для `StatefulSet` с `backup-store` нужен рабочий `StorageClass`. В `Minikube` он обычно доступен по умолчанию.
