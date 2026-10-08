# Payment Processing API

FastAPI module for making payments and managing in-memory transactions.

## Structure

- `main.py` creates the FastAPI app and registers routes.
- `models.py` contains request, response, transaction, and card validation models.
- `services.py` contains payment processing and transaction storage logic.
- `routes.py` contains API route handlers.
- `transaction_project/` contains Django project settings for transaction management.
- `transactions/` contains Django transaction models, filters, APIs, and tests.

## Run

```powershell
.\.venv\Scripts\uvicorn.exe main:app --reload
```

Swagger documentation is available at:

```text
http://127.0.0.1:8000/docs
```

## Endpoints

- `POST /payments` creates a transaction with `PENDING` status, simulates processing, then returns `SUCCESS` or `FAILED`.
- `GET /transactions/{transaction_id}` returns a single transaction.
- `GET /transactions` lists all transactions created since the app started.

## Django Transaction Management

Run migrations:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
```

Run the Django server:

```powershell
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8001
```

Django API endpoints:

- `GET /api/transactions/` returns the authenticated user's transaction history.
- `GET /api/transactions/{transaction_id}/` returns details for one owned transaction.

Supported history filters:

- `date=YYYY-MM-DD`
- `date_from=YYYY-MM-DD`
- `date_to=YYYY-MM-DD`
- `amount=1499.00`
- `min_amount=100.00`
- `max_amount=5000.00`
- `status=PENDING|SUCCESS|FAILED`
- `payment_status=PENDING|SUCCESS|FAILED`

These endpoints require Django authentication and always query with `user=request.user`, so users can only see their own transactions.

## Example Payment

```json
{
  "amount": "1499.00",
  "currency": "INR",
  "card": {
    "card_number": "4111111111111111",
    "card_holder_name": "Tharun Kumar",
    "expiry_month": 12,
    "expiry_year": 2030,
    "cvv": "123"
  }
}
```
