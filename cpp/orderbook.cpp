#include "orderbook.h"
#include <algorithm>
#include <cmath>
#include <numeric>

namespace orderbook {

// ============================================================
// Core operations
// ============================================================

uint64_t OrderBook::add_order(uint64_t id, Side side, double price, double size) {
    if (size <= 0.0) {
        throw std::invalid_argument("Order size must be positive");
    }
    if (price <= 0.0) {
        throw std::invalid_argument("Order price must be positive");
    }
    if (orders_.count(id)) {
        throw std::invalid_argument("Duplicate order ID");
    }

    Order order{id, side, price, size, size, next_timestamp_++};
    orders_[id] = order;

    if (side == Side::BUY) {
        auto& level = bids_[price];
        level.price = price;
        level.total_size += size;
        level.order_ids.push_back(id);
    } else {
        auto& level = asks_[price];
        level.price = price;
        level.total_size += size;
        level.order_ids.push_back(id);
    }

    return id;
}

bool OrderBook::cancel_order(uint64_t id) {
    auto it = orders_.find(id);
    if (it == orders_.end()) {
        return false;
    }

    remove_order_from_level(it->second);
    orders_.erase(it);
    return true;
}

bool OrderBook::modify_order(uint64_t id, double new_size) {
    auto it = orders_.find(id);
    if (it == orders_.end()) {
        return false;
    }
    if (new_size <= 0.0) {
        return cancel_order(id);
    }

    Order& order = it->second;
    double delta = new_size - order.size;

    // Update the price level's total size
    if (order.side == Side::BUY) {
        auto level_it = bids_.find(order.price);
        if (level_it != bids_.end()) {
            level_it->second.total_size += delta;
        }
    } else {
        auto level_it = asks_.find(order.price);
        if (level_it != asks_.end()) {
            level_it->second.total_size += delta;
        }
    }

    order.size = new_size;
    return true;
}

void OrderBook::remove_order_from_level(const Order& order) {
    if (order.side == Side::BUY) {
        auto level_it = bids_.find(order.price);
        if (level_it == bids_.end()) return;

        auto& level = level_it->second;
        level.total_size -= order.size;

        auto& ids = level.order_ids;
        ids.erase(std::remove(ids.begin(), ids.end(), order.id), ids.end());

        if (ids.empty() || level.total_size <= 1e-12) {
            bids_.erase(level_it);
        }
    } else {
        auto level_it = asks_.find(order.price);
        if (level_it == asks_.end()) return;

        auto& level = level_it->second;
        level.total_size -= order.size;

        auto& ids = level.order_ids;
        ids.erase(std::remove(ids.begin(), ids.end(), order.id), ids.end());

        if (ids.empty() || level.total_size <= 1e-12) {
            asks_.erase(level_it);
        }
    }
}

// ============================================================
// Market data queries
// ============================================================

TopOfBook OrderBook::top() const {
    TopOfBook tob{};

    tob.best_bid = 0.0;
    tob.best_bid_size = 0.0;
    tob.best_ask = std::numeric_limits<double>::max();
    tob.best_ask_size = 0.0;

    if (!bids_.empty()) {
        const auto& best = bids_.begin()->second;
        tob.best_bid = best.price;
        tob.best_bid_size = best.total_size;
    }
    if (!asks_.empty()) {
        const auto& best = asks_.begin()->second;
        tob.best_ask = best.price;
        tob.best_ask_size = best.total_size;
    }

    if (!bids_.empty() && !asks_.empty()) {
        tob.mid_price = (tob.best_bid + tob.best_ask) / 2.0;
        double total_size = tob.best_bid_size + tob.best_ask_size;
        if (total_size > 1e-12) {
            tob.micro_price = (
                tob.best_bid * tob.best_ask_size +
                tob.best_ask * tob.best_bid_size
            ) / total_size;
        } else {
            tob.micro_price = tob.mid_price;
        }
        tob.spread = tob.best_ask - tob.best_bid;
    } else if (!bids_.empty()) {
        tob.mid_price = tob.best_bid;
        tob.micro_price = tob.best_bid;
        tob.spread = 0.0;
    } else if (!asks_.empty()) {
        tob.mid_price = tob.best_ask;
        tob.micro_price = tob.best_ask;
        tob.spread = 0.0;
    } else {
        tob.mid_price = 0.0;
        tob.micro_price = 0.0;
        tob.spread = 0.0;
    }

    return tob;
}

template <typename MapType>
std::vector<DepthLevel> OrderBook::get_depth(
    const MapType& book, int levels
) const {
    std::vector<DepthLevel> result;
    result.reserve(levels);

    int count = 0;
    for (auto it = book.begin(); it != book.end() && count < levels; ++it, ++count) {
        result.push_back({
            it->second.price,
            it->second.total_size,
            static_cast<int>(it->second.order_ids.size())
        });
    }
    return result;
}

std::vector<DepthLevel> OrderBook::bid_depth(int levels) const {
    return get_depth(bids_, levels);
}

std::vector<DepthLevel> OrderBook::ask_depth(int levels) const {
    return get_depth(asks_, levels);
}

template <typename MapType>
double OrderBook::compute_vwap(const MapType& book, double target_size) const {
    double filled = 0.0;
    double cost = 0.0;

    for (auto it = book.begin(); it != book.end() && filled < target_size; ++it) {
        double available = it->second.total_size;
        double fill_qty = std::min(available, target_size - filled);
        cost += fill_qty * it->second.price;
        filled += fill_qty;
    }

    if (filled < 1e-12) {
        return 0.0;
    }
    return cost / filled;
}

double OrderBook::vwap(Side side, double target_size) const {
    if (side == Side::BUY) {
        // Buying sweeps the ask side (lowest prices first)
        return compute_vwap(asks_, target_size);
    } else {
        // Selling sweeps the bid side (highest prices first)
        return compute_vwap(bids_, target_size);
    }
}

template <typename MapType>
double OrderBook::get_volume_between(
    const MapType& book, double price_low, double price_high
) const {
    double vol = 0.0;
    for (auto it = book.begin(); it != book.end(); ++it) {
        double p = it->second.price;
        if (p >= price_low && p <= price_high) {
            vol += it->second.total_size;
        }
        // Optimization: for asks (ascending), break early if past high
        // For bids (descending), break early if below low
    }
    return vol;
}

double OrderBook::volume_between(
    Side side, double price_low, double price_high
) const {
    if (side == Side::BUY) {
        return get_volume_between(bids_, price_low, price_high);
    } else {
        return get_volume_between(asks_, price_low, price_high);
    }
}

double OrderBook::imbalance(int depth) const {
    auto bid_levels = bid_depth(depth);
    auto ask_levels = ask_depth(depth);

    double bid_vol = 0.0;
    double ask_vol = 0.0;

    for (const auto& l : bid_levels) bid_vol += l.size;
    for (const auto& l : ask_levels) ask_vol += l.size;

    double total = bid_vol + ask_vol;
    if (total < 1e-12) return 0.0;

    return (bid_vol - ask_vol) / total;
}

size_t OrderBook::level_count(Side side) const {
    return side == Side::BUY ? bids_.size() : asks_.size();
}

void OrderBook::clear() {
    bids_.clear();
    asks_.clear();
    orders_.clear();
    next_timestamp_ = 0;
}

} // namespace orderbook
