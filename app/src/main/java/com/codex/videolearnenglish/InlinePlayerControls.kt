package com.codex.videolearnenglish

import android.content.Context
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.view.GestureDetector
import android.view.Gravity
import android.view.MotionEvent
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.SeekBar
import android.widget.TextView

/** One gesture owner above the video, so a double tap cannot also trigger a single tap. */
internal class InlinePlayerControls(
    context: Context,
    progress: SeekBar,
    time: TextView,
    private val togglePlayback: () -> Unit,
    enterFullscreen: () -> Unit
) : FrameLayout(context) {
    private val bar = LinearLayout(context)
    private var playing = false
    private var seeking = false
    private val hide = Runnable { if (playing && !seeking) bar.visibility = INVISIBLE }
    private val play = action("▶", "学习视频播放或暂停") { togglePlayback(); showControls() }
    private val gestures = GestureDetector(context, object : GestureDetector.SimpleOnGestureListener() {
        override fun onDown(e: MotionEvent) = true
        override fun onSingleTapConfirmed(e: MotionEvent): Boolean { performClick(); return true }
        override fun onDoubleTap(e: MotionEvent): Boolean {
            togglePlayback(); showControls(); return true
        }
        override fun onDoubleTapEvent(e: MotionEvent) = true
    })

    init {
        contentDescription = "学习视频，单击显示控制栏，双击播放或暂停"
        bar.gravity = Gravity.CENTER_VERTICAL
        bar.setPadding(dp(4), dp(8), dp(4), 0)
        bar.background = GradientDrawable(GradientDrawable.Orientation.BOTTOM_TOP,
            intArrayOf(0xBB000000.toInt(), Color.TRANSPARENT))
        bar.addView(play, LinearLayout.LayoutParams(dp(44), dp(48)))
        progress.contentDescription = "学习视频播放进度"
        progress.setPadding(dp(6), 0, dp(6), 0)
        bar.addView(progress, LinearLayout.LayoutParams(0, dp(48), 1f))
        time.setTextColor(Color.WHITE)
        time.textSize = 11f
        time.setPadding(dp(4), 0, dp(4), 0)
        time.maxLines = 1
        bar.addView(time)
        bar.addView(action("⛶", "全屏播放", enterFullscreen), LinearLayout.LayoutParams(dp(44), dp(48)))
        addView(bar, LayoutParams(-1, -2, Gravity.BOTTOM))
        bar.visibility = INVISIBLE
    }

    override fun onTouchEvent(event: MotionEvent): Boolean { gestures.onTouchEvent(event); return true }
    override fun performClick(): Boolean {
        super.performClick()
        if (bar.visibility == VISIBLE) { bar.visibility = INVISIBLE; removeCallbacks(hide) }
        else showControls()
        return true
    }
    fun showControls() { bar.visibility = VISIBLE; scheduleHide() }
    fun resetControls() { bar.visibility = INVISIBLE; removeCallbacks(hide) }
    fun setSeeking(value: Boolean) { seeking = value; if (value) showControls() else scheduleHide() }
    fun updatePlayback(value: Boolean) {
        val changed = playing != value
        playing = value
        play.text = if (value) "Ⅱ" else "▶"
        if (changed) scheduleHide()
    }
    private fun scheduleHide() {
        removeCallbacks(hide)
        if (playing && !seeking && bar.visibility == VISIBLE) postDelayed(hide, 3000)
    }
    override fun onDetachedFromWindow() { removeCallbacks(hide); super.onDetachedFromWindow() }
    private fun action(label: String, description: String, action: () -> Unit) = TextView(context).apply {
        text = label; contentDescription = description; textSize = 22f
        gravity = Gravity.CENTER; setTextColor(Color.WHITE); isFocusable = true
        setOnClickListener { action() }
    }
    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
}
