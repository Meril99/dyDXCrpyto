#pragma once

#include <cstdint>
#include <map>
#include <string>
#include <unordered_map>
#include <vector>
#include <limits>
#include <stdexcept>

namespace orderbook {

enum class Side : uint8_t { BUY = 0, SELL = 1 };

struct Order {
    uint64_t    id;
    Side        side;
    double      price;
    double      size;        // remaining size
    double      original_size;
    uint64_t    timestamp;   // insertion order for FIFO within a level
};

struct PriceLevel {
    double                  price;
    double                  total_size;
    std::vector<uint64_t>   order_ids;   // FIFO queue of order IDs
};

struct TopOfBook {
    double best_bid;
    double best_bid_size;
    double best_ask;
    double best_ask_size;
    double mid_price;
    double micro_price;      // size-weighted mid
    double spread;
};

struct DepthLevel {
    double price;
    double size;
    int    order_count;
};

/// High-performance L2 order book with price-time priority.
///
/// Uses std::map for O(log N) sorted price levels and
/// an unordered_map for O(1) order lookup by ID.
///
/// Designed for incremental updates from a WebSocket feed.
class OrderBook {
public:
    OrderBook() : next_timestamp_(0) {}

    // ---- Core operations ----

    /// Add a new order. Returns the assigned order ID.
    uint64_t add_order(uint64_t id, Side side, double price, double size);

    /// Cancel an order by ID. Returns true if found and removed.
    bool cancel_order(uint64_t id);

    /// Modify an order's size (price change = cancel + add).
    /// Returns true if the order exists.
    bool modify_order(uint64_t id, double new_size);

    // ---- Market data queries ----

    /// Get top-of-book (BBO) snapshot.
    TopOfBook top() const;

    /// Get N levels of depth on the bid side.
    std::vector<DepthLevel> bid_depth(int levels) const;

    /// Get N levels of depth on the ask side.
    std::vector<DepthLevel> ask_depth(int levels) const;

    /// Volume-weighted average price for a given notional amount.
    /// Sweeps through the book from the best price.
    double vwap(Side side, double target_size) const;

    /// Total volume on a side within a price range.
    double volume_between(Side side, double price_low, double price_high) const;

    /// Orderbook imbalance: (bid_vol - ask_vol) / (bid_vol + ask_vol)
    /// over the top `depth` levels.
    double imbalance(int depth) const;

    // ---- Book state ----

    /// Total number of live orders.
    size_t order_count() const { return orders_.size(); }

    /// Number of distinct price levels on a side.
    size_t level_count(Side side) const;

    /// Clear all orders.
    void clear();

private:
    // Bids: highest price first (reverse order) => std::greater
    // Asks: lowest price first (natural order)
    using BidMap = std::map<double, PriceLevel, std::greater<double>>;
    using AskMap = std::map<double, PriceLevel>;

    BidMap  bids_;
    AskMap  asks_;

    // O(1) lookup: order_id -> Order
    std::unordered_map<uint64_t, Order> orders_;

    uint64_t next_timestamp_;

    // Internal helpers
    void remove_order_from_level(const Order& order);

    template <typename MapType>
    double compute_vwap(const MapType& book, double target_size) const;

    template <typename MapType>
    std::vector<DepthLevel> get_depth(const MapType& book, int levels) const;

    template <typename MapType>
    double get_volume_between(const MapType& book,
                              double price_low, double price_high) const;
};

} // namespace orderbook
