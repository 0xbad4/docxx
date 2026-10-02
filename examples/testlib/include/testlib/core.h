/**
 * @file core.h
 * @brief Core types for testlib.
 * @ingroup core
 */
#pragma once
#include <cstdint>
#include <string>
#include <vector>

/// Maximum number of widgets allowed at once.
#define TESTLIB_MAX_WIDGETS 64

/**
 * @def TESTLIB_CHECK(cond)
 * @brief Asserts a condition and returns false on failure.
 * @param cond the condition to check
 */
#define TESTLIB_CHECK(cond) do { if (!(cond)) return false; } while (0)

/**
 * @namespace testlib
 * @brief Root namespace for the whole library.
 */
namespace testlib {

/// Word type used throughout the VM.
using word_t = uint16_t;

/**
 * @brief Error codes returned by most operations.
 */
enum class error_type : uint8_t {
    NONE = 0,        ///< No error.
    BAD_ARG,         ///< An argument was invalid.
    OUT_OF_MEMORY,   ///< Allocation failed.
};

/// Convert an error_type to a human-readable string.
const char* err_str(error_type e);

/**
 * @brief A single widget in the system.
 *
 * Widgets are cheap value types; copy them freely.
 *
 * @note Widgets are not thread-safe. Guard access externally if shared
 * across threads.
 */
class Widget {
public:
    /// Constructs a widget with the given @p name.
    explicit Widget(std::string name);

    /**
     * @brief Destroys the widget.
     *
     * Any resources owned by the widget are released; this does not
     * affect other widgets that reference it.
     *
     * @note Safe to call even on a moved-from widget.
     */
    ~Widget();

    /**
     * @brief Renders the widget into @p buffer.
     *
     * The widget writes at most @p max_len bytes; callers should check the
     * return value against @p max_len to detect truncation.
     *
     * @param buffer destination buffer, must be non-null
     * @param max_len size of @p buffer in bytes
     * @return number of bytes written, or -1 on error
     * @note Increments render_calls even when it returns -1.
     */
    int render(char* buffer, int max_len) const;

    /// Widget display name.
    const std::string& name() const noexcept { return name_; }

    /// Sets the widget's visibility.
    void set_visible(bool v) noexcept { visible_ = v; }

    /// True if the widget is currently visible.
    bool visible() const noexcept { return visible_; }

    /// Number of widgets constructed so far, process-wide.
    static inline int live_count = 0;

    /// Number of times render() has been called; updated even on a const widget.
    mutable int render_calls = 0;

private:
    std::string name_;
    bool visible_ = true;
};

/**
 * @brief A widget that can contain other widgets.
 */
class Container : public Widget {
public:
    explicit Container(std::string name);

    /// Adds a child widget by name.
    void add_child(const std::string& name);
};

/**
 * @brief A scrollable container.
 */
class ScrollView : public Container {
public:
    explicit ScrollView(std::string name);
};

/**
 * @brief A generic fixed-capacity stack.
 * @tparam T element type
 * @tparam N maximum capacity
 */
template <typename T, int N = 16>
class FixedStack {
public:
    /// Pushes @p value; behavior is undefined if the stack is full.
    void push(const T& value);

    /// Pops and returns the top element.
    T pop();

    /// Number of elements currently stored.
    int size() const noexcept { return size_; }

private:
    T data_[N];
    int size_ = 0;
};

/**
 * @brief Runs the main widget loop.
 * @param widgets widgets to process
 * @param[out] error set on failure, may be null
 * @return true on success
 */
bool run(const std::vector<Widget>& widgets, error_type* error = nullptr);

/// @deprecated Use run() instead.
bool run_legacy(int argc, char** argv);

namespace detail {
/// Internal helper, not part of the public API.
void secret_helper();
}

} // namespace testlib
