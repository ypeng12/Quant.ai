// backend/app/cpp_engine/orderbook_pybind.cpp
/**
 * PyBind11 C++ Binding Wrapper for High-Frequency Limit Order Book.
 * Exposes C++17 LimitOrderBook, Order, Side, OrderType, and ExecutionReport to Python.
 */

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include "orderbook.hpp"

namespace py = pybind11;
using namespace HFT;

PYBIND11_MODULE(orderbook_cpp, m) {
    m.doc() = "C++17 High-Frequency Limit Order Book PyBind11 Extension Module";

    py::enum_<Side>(m, "Side")
        .value("BUY", Side::BUY)
        .value("SELL", Side::SELL)
        .export_values();

    py::enum_<OrderType>(m, "OrderType")
        .value("LIMIT", OrderType::LIMIT)
        .value("MARKET", OrderType::MARKET)
        .export_values();

    py::class_<Order>(m, "Order")
        .def(py::init<>())
        .def_readwrite("order_id", &Order::order_id)
        .def_readwrite("timestamp_ns", &Order::timestamp_ns)
        .def_readwrite("ticker_id", &Order::ticker_id)
        .def_readwrite("price", &Order::price)
        .def_readwrite("shares", &Order::shares)
        .def_readwrite("side", &Order::side)
        .def_readwrite("type", &Order::type);

    py::class_<ExecutionReport>(m, "ExecutionReport")
        .def(py::init<>())
        .def_readwrite("fill_id", &ExecutionReport::fill_id)
        .def_readwrite("buy_order_id", &ExecutionReport::buy_order_id)
        .def_readwrite("sell_order_id", &ExecutionReport::sell_order_id)
        .def_readwrite("fill_price", &ExecutionReport::fill_price)
        .def_readwrite("fill_shares", &ExecutionReport::fill_shares)
        .def_readwrite("timestamp_ns", &ExecutionReport::timestamp_ns);

    py::class_<LimitOrderBook>(m, "LimitOrderBook")
        .def(py::init<uint64_t>())
        .def("match_order", &LimitOrderBook::match_order, "Matches an incoming order and returns ExecutionReports")
        .def("get_best_bid", &LimitOrderBook::get_best_bid, "Returns highest current bid price")
        .def("get_best_ask", &LimitOrderBook::get_best_ask, "Returns lowest current ask price");
}
