
#pragma once
#include "testlib/core.h"

namespace testlib {

/**
 * @defgroup math Math helpers
 * @brief Small vector/matrix utilities.
 */

/**
 * @ingroup math
 * @brief A 2D vector of floats.
 * 
 * @markdown
 * # This is markdown
 * @markdownend
 */
struct Vec2 {
    float x = 0; ///< X component.
    float y = 0; ///< Y component.

    /// Adds two vectors component-wise.
    Vec2 operator+(const Vec2& rhs) const;

    /// In-place scalar multiply.
    Vec2& operator*=(float s);

    /// Implicit conversion to bool: true if non-zero.
    explicit operator bool() const;
};

/**
 * @ingroup math
 * @brief Clamps @p v between @p lo and @p hi.
 */
float clamp(float v, float lo, float hi);

/// Callback type invoked once per frame.
typedef void (*frame_callback_t)(double dt, void* userdata);

/**
 * @brief Installs a frame callback.
 * @param cb the callback, or nullptr to remove it
 * @param userdata opaque pointer passed back to @p cb
 */
void set_frame_callback(frame_callback_t cb, void* userdata = nullptr);

/**
 * @brief A tiny event dispatcher.
 */
class Dispatcher {
public:
    /**
     * @brief One registered listener.
     */
    struct Listener {
        int id;             ///< Unique listener id.
        bool once = false;  ///< Auto-unregister after first fire.
    };

    /// Registers a listener and returns its id.
    int subscribe(bool once = false);

    /// Removes a previously registered listener.
    void unsubscribe(int id);
};

} // namespace testlib
