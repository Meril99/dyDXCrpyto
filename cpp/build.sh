#!/bin/bash
# Build the C++ order book module.
# Usage: cd cpp && ./build.sh

set -e

BUILD_DIR="build"
mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"

cmake .. \
    -DCMAKE_BUILD_TYPE=Release \
    -DPYTHON_EXECUTABLE="$(which python3)"

make -j"$(nproc)"

# Copy the .so to the project root
cp orderbook_cpp*.so ../../

echo ""
echo "Build complete. Module copied to project root."
echo "Test with: python3 -c 'import orderbook_cpp; print(orderbook_cpp.OrderBook())'"
