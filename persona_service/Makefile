.PHONY: build up down logs restart clean start

build:
	docker-compose build

up:
	docker-compose up -d

down:
	docker-compose down

logs:
	docker-compose logs -f

restart:
	docker-compose restart

clean:
	docker-compose down -v

start: build up
	@echo "Persona service is running at http://localhost:5001"
	@echo "View logs with: make logs"

