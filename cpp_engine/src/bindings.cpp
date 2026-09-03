#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include "../include/fast_alpha_engine.hpp"
#include "../include/orderbook.hpp"
#include "../include/simd_alpha_calculator.hpp"
#include "../include/core/types.hpp"
#include "../include/order_book/order_book.hpp"
#include "../include/order_book/matching_engine.hpp"
#include "../include/risk/risk_engine.hpp"
#include "../include/engine/trading_engine.hpp"

namespace py = pybind11;
using namespace quant;

PYBIND11_MODULE(cpp_quant_engine, m) {
    m.doc() = "Quant.ai High-Performance C++20 Low-Latency Alpha & Production Trading Engine";

    // -------------------------------------------------------------
    // Legacy / Math Fast Alpha Bindings
    // -------------------------------------------------------------
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

    // -------------------------------------------------------------
    // Modern C++20 Core & Production Engine Bindings
    // -------------------------------------------------------------
    py::enum_<core::Side>(m, "Side")
        .value("BUY", core::Side::BUY)
        .value("SELL", core::Side::SELL)
        .value("UNKNOWN", core::Side::UNKNOWN);

    py::enum_<core::OrderType>(m, "OrderType")
        .value("LIMIT", core::OrderType::LIMIT)
        .value("MARKET", core::OrderType::MARKET)
        .value("IOC", core::OrderType::IOC)
        .value("FOK", core::OrderType::FOK);

    py::class_<core::Price>(m, "Price")
        .def(py::init<>())
        .def_static("from_double", &core::Price::from_double)
        .def_static("from_raw", &core::Price::from_raw)
        .def("to_double", &core::Price::to_double)
        .def("raw", &core::Price::raw);

    py::class_<order_book::OrderBook>(m, "OrderBook")
        .def("get_mid_price", &order_book::OrderBook::get_mid_price)
        .def("get_weighted_microprice", &order_book::OrderBook::get_weighted_microprice)
        .def("get_book_imbalance", &order_book::OrderBook::get_book_imbalance)
        .def("order_count", &order_book::OrderBook::order_count);

    py::class_<order_book::MatchingEngine>(m, "MatchingEngine")
        .def(py::init([](const std::string& symbol) {
            return std::make_unique<order_book::MatchingEngine>(core::Symbol(symbol.c_str()));
        }), py::arg("symbol") = "AAPL")
        .def("process_new_order", [](order_book::MatchingEngine& me, uint32_t client_id, uint64_t client_order_id,
                                     core::Side side, core::OrderType type, double price, uint32_t qty) {
            me.process_new_order(client_id, client_order_id, side, type, core::Price::from_double(price), qty, 0);
        })
        .def("cancel_order", &order_book::MatchingEngine::cancel_order,
             py::arg("client_id"), py::arg("client_order_id"), py::arg("engine_order_id") = 0, py::arg("timestamp_ns") = 0)
        .def("total_trades", &order_book::MatchingEngine::total_trades)
        .def("total_volume", &order_book::MatchingEngine::total_volume)
        .def("check_invariants", &order_book::MatchingEngine::check_invariants);

    py::class_<risk::RiskLimits>(m, "RiskLimits")
        .def(py::init<>())
        .def_readwrite("max_order_notional", &risk::RiskLimits::max_order_notional)
        .def_readwrite("price_collar_pct", &risk::RiskLimits::price_collar_pct)
        .def_readwrite("max_orders_per_sec", &risk::RiskLimits::max_orders_per_sec)
        .def_readwrite("max_net_position", &risk::RiskLimits::max_net_position);

    py::class_<engine::TradingEngine>(m, "TradingEngine")
        .def(py::init<>([](const std::string& symbol, uint16_t tcp_port, uint16_t udp_port) {
            engine::EngineConfig cfg;
            cfg.symbol = core::Symbol(symbol.c_str());
            cfg.tcp_port = tcp_port;
            cfg.udp_port = udp_port;
            return std::make_unique<engine::TradingEngine>(cfg);
        }), py::arg("symbol") = "AAPL", py::arg("tcp_port") = 9999, py::arg("udp_port") = 12345)
        .def("start", &engine::TradingEngine::start)
        .def("stop", &engine::TradingEngine::stop)
        .def("submit_order_direct", [](engine::TradingEngine& te, uint32_t client_id, uint64_t client_order_id,
                                       core::Side side, core::OrderType type, double price, uint32_t qty) {
            te.submit_order_direct(client_id, client_order_id, side, type, core::Price::from_double(price), qty);
        })
        .def("is_running", &engine::TradingEngine::is_running);
}
