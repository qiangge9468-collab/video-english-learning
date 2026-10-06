package com.codex.videolearnenglish

import android.content.Context
import android.graphics.Color
import android.graphics.Rect
import android.graphics.drawable.GradientDrawable
import android.text.Spanned
import android.text.style.ClickableSpan
import android.view.GestureDetector
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.SeekBar
import android.widget.TextView
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import kotlin.math.abs

/** Video never changes parent or SurfaceTexture when switching display modes. */
internal class FullscreenPlayerLayout(
    context: Context,
    private val page: View,
    private val video: View,
    private val slot: View,
    private val exit: () -> Unit,
    private val togglePlayback: () -> Unit,
    private val previousSentence: () -> Unit,
    private val nextSentence: () -> Unit,
    private val seek: (Int) -> Unit
) : FrameLayout(context) {
    var fullscreen = false
        private set
    val overlay = FrameLayout(context)
    val caption = DraggableCaption(context)
    private val preferences = context.getSharedPreferences("fullscreen_player", Context.MODE_PRIVATE)
    private val top = LinearLayout(context)
    private val bottom = LinearLayout(context)
    private val title = TextView(context)
    private val time = TextView(context)
    private val play = action("播放", "播放或暂停") { togglePlayback(); showControls() }
    private val progress = SeekBar(context)
    private val settings = LinearLayout(context)
    private val lock = action("锁定位置", "锁定字幕位置和大小") { setSubtitleLocked(!caption.locked) }
    private var playing = false
    private var duration = 0
    private var draggingSeek = false
    private var modalOpen = false
    private var controlsShown = false
    private val hideControls = Runnable { if (playing && !draggingSeek && !modalOpen) hideControls() }
    private var safe = Rect()
    private var fontSp = preferences.getFloat("font_sp", 22f).coerceIn(14f, 40f)
    private var lastCaption = ""
    private var captionFitKey = ""
    private val gestures = GestureDetector(context, object : GestureDetector.SimpleOnGestureListener() {
        override fun onDown(e: MotionEvent) = true
        override fun onSingleTapConfirmed(e: MotionEvent): Boolean {
            overlay.performClick()
            return true
        }
        override fun onDoubleTap(e: MotionEvent): Boolean {
            togglePlayback()
            showControls()
            return true
        }
        override fun onDoubleTapEvent(e: MotionEvent) = true
    })

    init {
        addView(page, LayoutParams(-1, -1))
        addView(video, LayoutParams(-1, -1))
        addView(overlay, LayoutParams(-1, -1))
        overlay.visibility = GONE
        overlay.setOnClickListener { if (controlsShown) hideControls() else showControls() }
        // Consume the whole stream, including the second UP of a double tap. It must
        // never fall through to the inline video's single-tap playback listener.
        overlay.setOnTouchListener { _, event -> gestures.onTouchEvent(event); true }
        caption.textSize = fontSp
        caption.visibility = GONE
        caption.position = FullscreenSubtitlePosition(
            preferences.getFloat("x", .5f), preferences.getFloat("y", .86f)
        )
        caption.locked = preferences.getBoolean("locked", false)
        caption.onPositionSaved = {
            preferences.edit().putFloat("x", it.x).putFloat("y", it.y).apply()
        }
        caption.onInteraction = { if (controlsShown) scheduleHide() }
        overlay.addView(caption, LayoutParams(-2, -2))
        top.gravity = Gravity.CENTER_VERTICAL
        top.background = GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM, intArrayOf(0x99000000.toInt(), Color.TRANSPARENT))
        top.addView(action("‹", "退出全屏", exit).apply { textSize = 30f }, LinearLayout.LayoutParams(dp(48), dp(48)))
        title.setTextColor(Color.WHITE)
        title.textSize = 16f
        title.maxLines = 1
        title.ellipsize = android.text.TextUtils.TruncateAt.END
        top.addView(title, LinearLayout.LayoutParams(0, dp(48), 1f))
        title.gravity = Gravity.CENTER_VERTICAL
        overlay.addView(top, LayoutParams(-1, -2, Gravity.TOP))

        bottom.orientation = LinearLayout.VERTICAL
        bottom.background = GradientDrawable(GradientDrawable.Orientation.BOTTOM_TOP, intArrayOf(0xCC000000.toInt(), Color.TRANSPARENT))
        val row = LinearLayout(context).apply { gravity = Gravity.CENTER_VERTICAL }
        row.addView(action("上句", "全屏上一句") { previousSentence(); showControls() }, LinearLayout.LayoutParams(dp(56), dp(48)))
        row.addView(play, LinearLayout.LayoutParams(dp(56), dp(48)))
        row.addView(action("下句", "全屏下一句") { nextSentence(); showControls() }, LinearLayout.LayoutParams(dp(56), dp(48)))
        row.addView(View(context), LinearLayout.LayoutParams(0, 1, 1f))
        time.setTextColor(Color.WHITE)
        time.textSize = 12f
        val seekRow = LinearLayout(context).apply { gravity = Gravity.CENTER_VERTICAL }
        progress.max = 10000
        progress.contentDescription = "全屏播放进度"
        seekRow.addView(progress, LinearLayout.LayoutParams(0, dp(36), 1f))
        time.setPadding(dp(8), 0, dp(8), 0)
        seekRow.addView(time)
        row.addView(action("字幕", "字幕大小和位置设置") {
            settings.visibility = if (settings.visibility == VISIBLE) GONE else VISIBLE
            showControls()
        }, LinearLayout.LayoutParams(dp(56), dp(48)))
        settings.gravity = Gravity.CENTER_VERTICAL or Gravity.END
        settings.addView(action("A−", "缩小字幕") { changeFont(-2f) }, LinearLayout.LayoutParams(dp(52), dp(48)))
        settings.addView(action("A+", "放大字幕") { changeFont(2f) }, LinearLayout.LayoutParams(dp(52), dp(48)))
        settings.addView(lock, LinearLayout.LayoutParams(dp(100), dp(48)))
        settings.addView(action("复位", "恢复字幕默认位置和大小") {
            if (!caption.locked) {
                fontSp = 22f
                caption.textSize = fontSp
                caption.position = FullscreenSubtitlePosition()
                caption.onPositionSaved(caption.position)
                preferences.edit().putFloat("font_sp", fontSp).apply()
                requestLayout()
            }
            showControls()
        }, LinearLayout.LayoutParams(dp(56), dp(48)))
        settings.visibility = GONE
        bottom.addView(settings)
        bottom.addView(seekRow)
        bottom.addView(row)
        overlay.addView(bottom, LayoutParams(-1, -2, Gravity.BOTTOM))
        setSubtitleLocked(caption.locked)
        progress.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onStartTrackingTouch(bar: SeekBar?) {
                draggingSeek = true
                removeCallbacks(hideControls)
            }
            override fun onProgressChanged(bar: SeekBar?, value: Int, fromUser: Boolean) {
                if (fromUser) time.text = timeText((duration.toLong() * value / 10000).toInt(), duration)
            }
            override fun onStopTrackingTouch(bar: SeekBar?) {
                if (duration > 0) seek((duration.toLong() * (bar?.progress ?: 0) / 10000).toInt())
                draggingSeek = false
                scheduleHide()
            }
        })
        ViewCompat.setOnApplyWindowInsetsListener(this) { _, insets ->
            // Hidden bars occupy no space. Only an actual cutout or currently visible
            // system bar is reserved, and only inside the chrome (not its background).
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            val cutout = insets.getInsetsIgnoringVisibility(WindowInsetsCompat.Type.displayCutout())
            safe = Rect(maxOf(bars.left, cutout.left), maxOf(bars.top, cutout.top),
                maxOf(bars.right, cutout.right), maxOf(bars.bottom, cutout.bottom))
            top.setPadding(safe.left + dp(8), safe.top + dp(4), safe.right + dp(8), dp(4))
            bottom.setPadding(safe.left + dp(8), 0, safe.right + dp(8), safe.bottom + dp(4))
            requestLayout()
            insets
        }
    }

    fun setFullscreen(value: Boolean, videoTitle: String = "") {
        fullscreen = value
        page.visibility = if (value) INVISIBLE else VISIBLE
        overlay.visibility = if (value) VISIBLE else GONE
        title.text = videoTitle
        if (value) showControls() else removeCallbacks(hideControls)
        requestLayout()
        ViewCompat.requestApplyInsets(this)
    }

    fun updateCaption(text: CharSequence?) {
        val plain = text?.toString().orEmpty()
        if (plain == lastCaption) return
        lastCaption = plain
        caption.text = text ?: ""
        caption.visibility = if (plain.isBlank()) GONE else VISIBLE
        requestLayout()
    }

    fun updatePlayback(isPlaying: Boolean, positionMs: Int, durationMs: Int) {
        val changed = playing != isPlaying
        playing = isPlaying
        duration = durationMs.coerceAtLeast(0)
        val label = if (playing) "暂停" else "播放"
        if (play.text != label) play.text = label
        if (!draggingSeek) {
            val text = timeText(positionMs, duration)
            if (time.text != text) time.text = text
            progress.progress = if (duration > 0) (positionMs.toLong() * 10000 / duration).toInt() else 0
        }
        if (changed && fullscreen) {
            if (!playing) showControls() else scheduleHide()
        }
    }

    fun setModalOpen(value: Boolean) {
        modalOpen = value
        if (value) removeCallbacks(hideControls) else scheduleHide()
    }

    fun showControls() {
        controlsShown = true
        top.visibility = VISIBLE
        bottom.visibility = VISIBLE
        scheduleHide()
    }

    private fun hideControls() {
        controlsShown = false
        top.visibility = INVISIBLE
        bottom.visibility = INVISIBLE
        settings.visibility = GONE
        removeCallbacks(hideControls)
    }

    private fun scheduleHide() {
        removeCallbacks(hideControls)
        if (fullscreen && playing && controlsShown && !modalOpen && !draggingSeek && settings.visibility != VISIBLE) {
            postDelayed(hideControls, 3000)
        }
    }

    private fun setSubtitleLocked(locked: Boolean) {
        caption.locked = locked
        lock.text = if (locked) "解锁位置" else "锁定位置"
        lock.contentDescription = if (locked) "解锁字幕位置和大小" else "锁定字幕位置和大小"
        preferences.edit().putBoolean("locked", locked).apply()
        for (i in 0 until settings.childCount) {
            val child = settings.getChildAt(i)
            if (child !== lock) { child.isEnabled = !locked; child.alpha = if (locked) .4f else 1f }
        }
    }

    private fun changeFont(delta: Float) {
        if (!caption.locked) {
            fontSp = (fontSp + delta).coerceIn(14f, 40f)
            caption.textSize = fontSp
            preferences.edit().putFloat("font_sp", fontSp).apply()
            requestLayout()
        }
        showControls()
    }

    override fun onLayout(changed: Boolean, left: Int, topPx: Int, right: Int, bottomPx: Int) {
        // Lay out the video exactly once at its final bounds, avoiding transient full-size
        // TextureView callbacks when the inline page requests a subtitle/progress update.
        page.layout(0, 0, width, height)
        val bounds = Rect(0, 0, width, height)
        if (!fullscreen) {
            bounds.set(0, 0, slot.width, slot.height)
            offsetDescendantRectToMyCoords(slot, bounds)
        }
        video.measure(MeasureSpec.makeMeasureSpec(bounds.width(), MeasureSpec.EXACTLY), MeasureSpec.makeMeasureSpec(bounds.height(), MeasureSpec.EXACTLY))
        video.layout(bounds.left, bounds.top, bounds.right, bounds.bottom)
        overlay.layout(0, 0, width, height)
        if (fullscreen) {
            // Keep the expanded size/lock panel clear of the caption too. The saved
            // normalized position is unchanged when this temporary panel closes.
            val bottomClearance = if (controlsShown && settings.visibility == VISIBLE) 140 else 92
            val area = Rect(safe.left + dp(16), safe.top + dp(60), width - safe.right - dp(16), height - safe.bottom - dp(bottomClearance))
            val maxWidth = (area.width() * .9f).toInt().coerceAtLeast(1)
            val maxHeight = area.height().coerceAtLeast(1)
            fun measureCaption() = caption.measure(MeasureSpec.makeMeasureSpec(maxWidth, MeasureSpec.AT_MOST), MeasureSpec.makeMeasureSpec(0, MeasureSpec.UNSPECIFIED))
            val fitKey = "$maxWidth:$maxHeight:$fontSp:${caption.text}"
            if (captionFitKey != fitKey) {
                captionFitKey = fitKey
                caption.textSize = fontSp
                measureCaption()
                var fittedSp = fontSp
                while (caption.measuredHeight > maxHeight && fittedSp > 10f) {
                    fittedSp -= 1f
                    caption.textSize = fittedSp
                    measureCaption()
                }
            } else {
                measureCaption()
            }
            caption.travelBounds = Rect(area.left, area.top, (area.right - caption.measuredWidth).coerceAtLeast(area.left), (area.bottom - caption.measuredHeight).coerceAtLeast(area.top))
            val (x, y) = caption.position.pixels(caption.travelBounds.width(), caption.travelBounds.height())
            caption.layout(area.left + x, area.top + y, area.left + x + caption.measuredWidth, area.top + y + caption.measuredHeight)
        }
    }

    override fun onDetachedFromWindow() {
        removeCallbacks(hideControls)
        super.onDetachedFromWindow()
    }

    private fun action(label: String, description: String, action: () -> Unit) = TextView(context).apply {
        text = label
        contentDescription = description
        textSize = 16f
        gravity = Gravity.CENTER
        setTextColor(Color.WHITE)
        isFocusable = true
        setOnClickListener { action() }
    }
    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
    private fun timeText(position: Int, duration: Int): String {
        fun format(ms: Int): String { val s = ms.coerceAtLeast(0) / 1000; return "%02d:%02d".format(s / 60, s % 60) }
        return "${format(position)} / ${format(duration)}"
    }
}

/** Drag threshold and explicit span hit testing prevent a drag from triggering dictionary lookup. */
// LearningActivity uses the platform Activity/Material theme, not AppCompatActivity.
// This caption needs no AppCompat tinting and must retain the platform TextView behavior.
@android.annotation.SuppressLint("AppCompatCustomView")
internal class DraggableCaption(context: Context) : TextView(context) {
    var locked = false
    var position = FullscreenSubtitlePosition()
    var travelBounds = Rect()
    var onPositionSaved: (FullscreenSubtitlePosition) -> Unit = {}
    var onInteraction: () -> Unit = {}
    private val slop = ViewConfiguration.get(context).scaledTouchSlop
    private var downX = 0f
    private var downY = 0f
    private var originalX = 0
    private var originalY = 0
    private var moved = false
    private var pressedSpan: ClickableSpan? = null
    init {
        contentDescription = "当前句字幕，可拖动，点词查词"
        gravity = Gravity.CENTER
        setTextColor(Color.WHITE)
        setShadowLayer(3f, 0f, 1f, Color.BLACK)
        setPadding(12, 6, 12, 6)
        setBackgroundColor(0x66000000)
    }
    override fun onTouchEvent(event: MotionEvent): Boolean {
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                downX = event.rawX; downY = event.rawY; originalX = left; originalY = top
                moved = false; pressedSpan = spanAt(event.x, event.y)
                parent.requestDisallowInterceptTouchEvent(true)
                onInteraction()
            }
            MotionEvent.ACTION_MOVE -> {
                val dx = event.rawX - downX; val dy = event.rawY - downY
                if (abs(dx) > slop || abs(dy) > slop) moved = true
                if (moved && !locked) {
                    val x = (originalX + dx).toInt().coerceIn(travelBounds.left, travelBounds.right)
                    val y = (originalY + dy).toInt().coerceIn(travelBounds.top, travelBounds.bottom)
                    position = FullscreenSubtitlePosition.fromPixels((x - travelBounds.left).toFloat(), (y - travelBounds.top).toFloat(), travelBounds.width(), travelBounds.height())
                    layout(x, y, x + width, y + height)
                }
            }
            MotionEvent.ACTION_UP -> {
                if (moved) { if (!locked) onPositionSaved(position) }
                else if (pressedSpan != null && pressedSpan === spanAt(event.x, event.y)) pressedSpan?.onClick(this)
                else performClick()
                parent.requestDisallowInterceptTouchEvent(false)
            }
            MotionEvent.ACTION_CANCEL -> { pressedSpan = null; parent.requestDisallowInterceptTouchEvent(false) }
        }
        return true
    }
    override fun performClick(): Boolean { super.performClick(); return true }
    private fun spanAt(x: Float, y: Float): ClickableSpan? {
        val text = text as? Spanned ?: return null
        val layout = layout ?: return null
        val localX = x - totalPaddingLeft + scrollX
        val localY = y - totalPaddingTop + scrollY
        if (localY < 0 || localY >= layout.height) return null
        val line = layout.getLineForVertical(localY.toInt())
        if (localX < layout.getLineLeft(line) || localX > layout.getLineRight(line)) return null
        val offset = layout.getOffsetForHorizontal(line, localX)
        return text.getSpans(offset, offset, ClickableSpan::class.java).firstOrNull()
    }
}
