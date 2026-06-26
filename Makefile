.PHONY: compile test docker-build docker-smoke docker-production-smoke release-check

DOCKER_RUN_HARDENING = --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m --cap-drop ALL --security-opt no-new-privileges

compile:
	python3 -m py_compile launch_android_app.py $$(find sla_launcher sla_app scripts -name '*.py')

test:
	python3 -m pytest tests

docker-build:
	docker build --build-arg SLA_BUILD_SHA=$$(git rev-parse --short HEAD 2>/dev/null || echo local) -t hspace-sla-runner:verify .

docker-smoke: docker-build
	sh -c 'set -e; trap "docker rm -f hspace-sla-verify >/dev/null 2>&1 || true" EXIT; docker rm -f hspace-sla-verify >/dev/null 2>&1 || true; docker run -d --name hspace-sla-verify $(DOCKER_RUN_HARDENING) -p 127.0.0.1::8000 -e SLA_START_APPIUM=false hspace-sla-runner:verify; port=$$(docker port hspace-sla-verify 8000/tcp | sed "s/.*://"); base="http://127.0.0.1:$${port}"; for i in $$(seq 1 15); do curl -fsS "$${base}/healthz" >/dev/null 2>&1 && break; sleep 1; done; curl -fsS "$${base}/healthz"; curl -fsS "$${base}/readyz"; curl -fsS "$${base}/version"; curl -fsS "$${base}/metrics"'

docker-production-smoke: docker-build
	sh -c 'set -e; password=verify-production-password-32chars; csrf=verify-production-csrf-secret-32chars; trap "docker rm -f hspace-sla-prod-verify >/dev/null 2>&1 || true" EXIT; docker rm -f hspace-sla-prod-verify >/dev/null 2>&1 || true; docker run -d --name hspace-sla-prod-verify $(DOCKER_RUN_HARDENING) -p 127.0.0.1::8000 -e SLA_ENV=production -e SLA_BUILD_SHA=verify -e SLA_START_APPIUM=false -e SLA_BASIC_AUTH_USER=operator -e SLA_BASIC_AUTH_PASSWORD=$${password} -e SLA_CSRF_SECRET=$${csrf} -e SLA_TRUSTED_ORIGINS=http://127.0.0.1 -e SLA_ALLOWED_HOSTS=127.0.0.1,localhost hspace-sla-runner:verify; port=$$(docker port hspace-sla-prod-verify 8000/tcp | sed "s/.*://"); base="http://127.0.0.1:$${port}"; for i in $$(seq 1 15); do curl -fsS "$${base}/healthz" >/dev/null 2>&1 && break; sleep 1; done; curl -fsS "$${base}/healthz"; curl -fsS "$${base}/readyz"; test "$$(curl -s -o /dev/null -w "%{http_code}" "$${base}/version")" = "401"; curl -fsS -u operator:$${password} "$${base}/version" | grep -q "\"deployment_config_ok\":true"; test "$$(curl -s -o /dev/null -w "%{http_code}" "$${base}/metrics")" = "401"; curl -fsS -u operator:$${password} "$${base}/metrics" | grep -q "sla_info"'

release-check: compile test docker-smoke docker-production-smoke
	docker compose config
