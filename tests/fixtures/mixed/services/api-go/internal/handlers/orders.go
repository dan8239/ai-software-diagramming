package handlers

import (
	"encoding/json"
	"net/http"

	"github.com/acme/mono/services/api/internal/store"
)

type Handler struct{ s *store.Store }

func New(s *store.Store) *Handler { return &Handler{s: s} }

func (h *Handler) ListOrders(w http.ResponseWriter, r *http.Request) {
	orders, _ := h.s.List(r.Context())
	json.NewEncoder(w).Encode(orders)
}
