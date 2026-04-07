#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include "orderbook.h"

namespace py = pybind11;
using namespace orderbook;

PYBIND11_MODULE(orderbook_cpp, m) {
    m.doc() = "High-performance C++ order book engine with Python bindings";

    // ---- Enums ----
    py::enum_<Side>(m, "Side")
        .value("BUY", Side::BUY)
        .value("SELL", Side::SELL)
        .export_values();

    // ---- Data structures ----
    py::class_<TopOfBook>(m, "TopOfBook")
        .def_readonly("best_bid", &TopOfBook::best_bid)
        .def_readonly("best_bid_size", &TopOfBook::best_bid_size)
        .def_readonly("best_ask", &TopOfBook::best_ask)
        .def_readonly("best_ask_size", &TopOfBook::best_ask_size)
        .def_readonly("mid_price", &TopOfBook::mid_price)
        .def_readonly("micro_price", &TopOfBook::micro_price)
        .def_readonly("spread", &TopOfBook::spread)
        .def("__repr__", [](const TopOfBook& t) {
            return "<TopOfBook bid=" + std::to_string(t.best_bid) +
                   " ask=" + std::to_string(t.best_ask) +
                   " mid=" + std::to_string(t.mid_price) +
                   " spread=" + std::to_string(t.spread) + ">";
        });

    py::class_<DepthLevel>(m, "DepthLevel")
        .def_readonly("price", &DepthLevel::price)
        .def_readonly("size", &DepthLevel::size)
        .def_readonly("order_count", &DepthLevel::order_count)
        .def("__repr__", [](const DepthLevel& d) {
            return "<DepthLevel price=" + std::to_string(d.price) +
                   " size=" + std::to_string(d.size) +
                   " orders=" + std::to_string(d.order_count) + ">";
        });

    // ---- OrderBook class ----
    py::class_<OrderBook>(m, "OrderBook")
        .def(py::init<>())

        // Core operations
        .def("add_order", &OrderBook::add_order,
             py::arg("id"), py::arg("side"), py::arg("price"), py::arg("size"),
             "Add a new order to the book. Raises on duplicate ID.")
        .def("cancel_order", &OrderBook::cancel_order,
             py::arg("id"),
             "Cancel an order by ID. Returns True if found.")
        .def("modify_order", &OrderBook::modify_order,
             py::arg("id"), py::arg("new_size"),
             "Modify an order's remaining size. Cancels if new_size <= 0.")

        // Market data
        .def("top", &OrderBook::top,
             "Get top-of-book snapshot (BBO, mid, micro-price, spread).")
        .def("bid_depth", &OrderBook::bid_depth,
             py::arg("levels") = 10,
             "Get N levels of bid depth.")
        .def("ask_depth", &OrderBook::ask_depth,
             py::arg("levels") = 10,
             "Get N levels of ask depth.")
        .def("vwap", &OrderBook::vwap,
             py::arg("side"), py::arg("target_size"),
             "VWAP for sweeping a given size through the book.")
        .def("volume_between", &OrderBook::volume_between,
             py::arg("side"), py::arg("price_low"), py::arg("price_high"),
             "Total volume within a price range on one side.")
        .def("imbalance", &OrderBook::imbalance,
             py::arg("depth") = 10,
             "Orderbook imbalance over top N levels. Range [-1, 1].")

        // State
        .def("order_count", &OrderBook::order_count,
             "Total number of live orders.")
        .def("level_count", &OrderBook::level_count,
             py::arg("side"),
             "Number of distinct price levels on a side.")
        .def("clear", &OrderBook::clear,
             "Remove all orders.")
        .def("__len__", &OrderBook::order_count)
        .def("__repr__", [](const OrderBook& ob) {
            auto t = ob.top();
            return "<OrderBook orders=" + std::to_string(ob.order_count()) +
                   " bid=" + std::to_string(t.best_bid) +
                   " ask=" + std::to_string(t.best_ask) +
                   " spread=" + std::to_string(t.spread) + ">";
        });
}
