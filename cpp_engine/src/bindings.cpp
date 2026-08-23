#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include "../include/fast_alpha_engine.hpp"
#include "../include/orderbook.hpp"
#include "../include/simd_alpha_calculator.hpp"

namespace py = pybind11;
using namespace quant;

PYBIND11_MODULE(cpp_quant_engine, m) {
    m.doc() = "Quant.ai High-Performance C++ Low-Latency Alpha & Order Book Engine";

    py::class_<MarketTick>(m, "MarketTick")
        .def(py::init<double, double, double, double, double, double, double>(),
             py::arg("timestamp") = 0.0,
             py::arg("bid_price") = 0.0,
             py::arg("ask_price") = 0.0,
             py::arg("bid_size") = 0.0,
             py::arg("ask_size") = 0.0,
             py::arg("last_price") = 0.0,
             py::arg("last_volume") = 0.0)
        .def_readwrite("timestamp", &MarketTick::timestamp)
        .def_readwrite("bid_price", &MarketTick::bid_price)
        .def_readwrite("ask_price", &MarketTick::ask_price)
        .def_readwrite("bid_size", &MarketTick::bid_size)
        .def_readwrite("ask_size", &MarketTick::ask_size)
        .def_readwrite("last_price", &MarketTick::last_price)
        .def_readwrite("last_volume", &MarketTick::last_volume);

    py::class_<AlphaSignalPayload>(m, "AlphaSignalPayload")
        .def_readonly("micro_price", &AlphaSignalPayload::micro_price)
        .def_readonly("order_book_imbalance", &AlphaSignalPayload::order_book_imbalance)
        .def_readonly("vwap", &AlphaSignalPayload::vwap)
        .def_readonly("rolling_volatility", &AlphaSignalPayload::rolling_volatility)
        .def_readonly("ema_9", &AlphaSignalPayload::ema_9)
        .def_readonly("ema_21", &AlphaSignalPayload::ema_21)
        .def_readonly("signal_score", &AlphaSignalPayload::signal_score);

    py::class_<FastAlphaEngine>(m, "FastAlphaEngine")
        .def(py::init<int>(), py::arg("window_size") = 20)
        .def("process_tick", &FastAlphaEngine::process_tick, py::arg("tick"))
        .def_static("calculate_micro_price", &FastAlphaEngine::calculate_micro_price)
        .def_static("calculate_obi", &FastAlphaEngine::calculate_obi)
        .def_static("fast_ema", &FastAlphaEngine::fast_ema)
        .def_static("fast_vwap", &FastAlphaEngine::fast_vwap)
        .def_static("fast_order_flow_imbalance", &FastAlphaEngine::fast_order_flow_imbalance);

    py::class_<FastL2OrderBook>(m, "FastL2OrderBook")
        .def(py::init<>())
        .def("update_bid", &FastL2OrderBook::update_bid, py::arg("level"), py::arg("price"), py::arg("volume"), py::arg("count") = 1)
        .def("update_ask", &FastL2OrderBook::update_ask, py::arg("level"), py::arg("price"), py::arg("volume"), py::arg("count") = 1)
        .def("get_best_bid", &FastL2OrderBook::get_best_bid)
        .def("get_best_ask", &FastL2OrderBook::get_best_ask)
        .def("get_mid_price", &FastL2OrderBook::get_mid_price)
        .def("get_weighted_microprice", &FastL2OrderBook::get_weighted_microprice)
        .def("calculate_book_imbalance", &FastL2OrderBook::calculate_book_imbalance);

    py::class_<SIMDAlphaCalculator>(m, "SIMDAlphaCalculator")
        .def_static("calculate_ofi_vectorized", &SIMDAlphaCalculator::calculate_ofi_vectorized)
        .def_static("calculate_microprice_velocity", &SIMDAlphaCalculator::calculate_microprice_velocity)
        .def_static("calculate_vpin_toxicity", &SIMDAlphaCalculator::calculate_vpin_toxicity);
}
