package main

import (
	"database/sql"
	"net/http"

	"github.com/gorilla/mux"
	_ "github.com/lib/pq"

	"github.com/acme/mono/services/api/internal/handlers"
	"github.com/acme/mono/services/api/internal/store"
)

func main() {
	r := mux.NewRouter()
	db, _ := sql.Open("postgres", "postgres://...")
	s := store.New(db)
	h := handlers.New(s)
	r.HandleFunc("/orders", h.ListOrders)
	http.ListenAndServe(":8080", r)
}
