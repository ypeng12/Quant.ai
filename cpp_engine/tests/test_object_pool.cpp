#include <gtest/gtest.h>
#include "../include/core/object_pool.hpp"

using namespace quant::core;

struct TestItem {
    int id;
    double value;
    TestItem(int i, double v) : id(i), value(v) {}
};

TEST(ObjectPoolTest, AllocationAndRecycle) {
    ObjectPool<TestItem, 4> pool;
    EXPECT_EQ(pool.allocated_count(), 0);
    EXPECT_EQ(pool.available_count(), 4);

    TestItem* a = pool.allocate(1, 10.5);
    TestItem* b = pool.allocate(2, 20.5);
    TestItem* c = pool.allocate(3, 30.5);
    TestItem* d = pool.allocate(4, 40.5);

    EXPECT_NE(a, nullptr);
    EXPECT_NE(b, nullptr);
    EXPECT_NE(c, nullptr);
    EXPECT_NE(d, nullptr);
    EXPECT_EQ(pool.allocated_count(), 4);

    // Exhausted
    TestItem* e = pool.allocate(5, 50.5);
    EXPECT_EQ(e, nullptr);

    // Deallocate b and reallocate
    pool.deallocate(b);
    EXPECT_EQ(pool.allocated_count(), 3);

    TestItem* f = pool.allocate(6, 60.5);
    EXPECT_NE(f, nullptr);
    EXPECT_EQ(f->id, 6);

    pool.deallocate(a);
    pool.deallocate(c);
    pool.deallocate(d);
    pool.deallocate(f);
    EXPECT_EQ(pool.allocated_count(), 0);
}

TEST(ObjectPoolTest, RAIIUniquePtr) {
    ObjectPool<TestItem, 2> pool;
    {
        auto ptr = pool.make_unique(100, 99.9);
        EXPECT_NE(ptr.get(), nullptr);
        EXPECT_EQ(ptr->id, 100);
        EXPECT_EQ(pool.allocated_count(), 1);
    }
    // Automatically recycled upon leaving scope
    EXPECT_EQ(pool.allocated_count(), 0);
}
