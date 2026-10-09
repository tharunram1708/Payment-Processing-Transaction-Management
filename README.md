# Payment Processing API

FastAPI processes payments and writes the resulting transactions into the Django database.
Django provides authenticated transaction history and transaction detail APIs.

## Structure

- `main.py` creates the FastAPI app and registers routes.
- `models.py` contains request, response, transaction, and card validation models.
- `services.py` contains payment processing logic and writes to the Django `Transaction` model.
- `routes.py` contains API route handlers.
- `transaction_project/` contains Django project settings for transaction management.
- `transactions/` contains Django transaction models, filters, APIs, and tests.

## Run

FastAPI and Django use the same SQLite database through Django's ORM. Run migrations first:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
```

Create a Django user before posting payments. The FastAPI request needs that user's `user_id`.

```powershell
.\.venv\Scripts\python.exe manage.py createsuperuser
```

Run FastAPI:

```powershell
.\.venv\Scripts\uvicorn.exe main:app --reload
```

Swagger documentation is available at:

```text
http://127.0.0.1:8000/docs
```

## Endpoints

- `POST /payments` creates a transaction with `PENDING` status, simulates processing, then returns `SUCCESS` or `FAILED`.
- `GET /transactions/{transaction_id}` returns a single transaction from the Django database.
- `GET /transactions` lists all transactions from the Django database.

## Django Transaction Management

Run the Django server:

```powershell
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8001
```

Django API endpoints:

- `POST /api/auth/register/` creates a user with Django password hashing and returns a JWT access token.
- `POST /api/auth/login/` validates username/password credentials and returns a JWT access token.
- `POST /api/auth/logout/` revokes the current JWT access token.
- `GET /api/auth/me/` returns the current authenticated user.
- `POST /api/cards/` saves a credit/debit card as masked card data only.
- `GET /api/cards/` lists the authenticated user's saved cards.
- `DELETE /api/cards/{card_id}/` deletes one owned saved card.
- `GET /api/transactions/` returns the authenticated user's transaction history.
- `GET /api/transactions/{transaction_id}/` returns details for one owned transaction.

Use the returned token on protected routes:

```text
Authorization: Bearer <access_token>
```

Example card request:

```json
{
  "card_number": "4111111111111111",
  "card_holder_name": "Tharun Kumar",
  "card_type": "CREDIT",
  "expiry_month": 12,
  "expiry_year": 2030
}
```

The card number is used only to create `masked_card_number` and `last4`. The database model does not store full card numbers or CVV values.

Browser template pages:

- `GET /register/` displays the registration page.
- `GET /login/` displays the login page.
- `POST /logout/` logs out the current browser session.
- `GET /cards/` displays saved cards and the add-card form.
- `POST /cards/` saves a masked card for the current user.
- `POST /cards/{card_id}/delete/` deletes one owned saved card.

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
  "user_id": 1,
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
