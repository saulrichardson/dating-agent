.PHONY: build up down logs restart clean

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
	rm -f context_storage.json

start: build up
	@echo "Context service is running at http://localhost:5000"
	@echo "View logs with: make logs"




