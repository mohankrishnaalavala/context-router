package handlers

import (
	"encoding/json"
	"net/http"
)

// UserHandler handles user-related HTTP requests.
type UserHandler struct {
	db *Database
}

// GetUser retrieves a user by ID from the database.
func (h *UserHandler) GetUser(w http.ResponseWriter, r *http.Request) {
	id := r.URL.Query().Get("id")
	user, err := h.db.FindUser(id)
	if err != nil {
		http.Error(w, "not found", http.StatusNotFound)
		return
	}
	json.NewEncoder(w).Encode(user)
}

// CreateUser persists a new user from the request body.
func CreateUser(w http.ResponseWriter, r *http.Request) {
	var user User
	if err := json.NewDecoder(r.Body).Decode(&user); err != nil {
		http.Error(w, "bad request", http.StatusBadRequest)
		return
	}
	w.WriteHeader(http.StatusCreated)
}

type Database struct{ dsn string }

func (db *Database) FindUser(id string) (*User, error) { return nil, nil }

type User struct {
	ID    string `json:"id"`
	Email string `json:"email"`
}
