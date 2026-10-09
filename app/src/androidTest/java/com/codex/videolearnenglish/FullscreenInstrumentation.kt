package com.codex.videolearnenglish

import android.app.Activity
import android.app.Instrumentation
import android.content.Intent
import android.content.pm.ActivityInfo
import android.graphics.Bitmap
import android.media.MediaPlayer
import android.os.Bundle
import android.os.SystemClock
import android.text.Spanned
import android.text.style.ClickableSpan
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import java.io.BufferedReader
import java.io.File
import java.io.StringReader
import kotlin.math.abs

/** Real emulator/device regression. Uses an existing local video; no network/ASR or app test hooks. */
class FullscreenInstrumentation : Instrumentation() {
    private lateinit var activity: LearningActivity
    private var count = 0
    private var failed = 0
    private val messages = StringBuilder()
    private fun field(name: String): Any? = LearningActivity::class.java.getDeclaredField(name).apply { isAccessible = true }.get(activity)
    private fun set(name: String, value: Any?) = LearningActivity::class.java.getDeclaredField(name).apply { isAccessible = true }.set(activity, value)
    private fun call(name: String, vararg args: Any?): Any? = LearningActivity::class.java.declaredMethods.first { it.name == name && it.parameterCount == args.size }.apply { isAccessible = true }.invoke(activity, *args)
    private fun ui(block: () -> Unit) {
        var failure: Throwable? = null
        runOnMainSync { try { block() } catch (e: Throwable) { failure = e } }
        waitForIdleSync()
        failure?.let { throw it }
    }
    private fun player() = field("mediaPlayer") as MediaPlayer
    private fun layout() = field("fullscreenPlayer") as FullscreenPlayerLayout
    private fun checkThat(value: Boolean, message: String) { if (!value) throw AssertionError(message) }
    private fun await(message: String, condition: () -> Boolean) {
        val deadline = SystemClock.uptimeMillis() + 12000
        while (SystemClock.uptimeMillis() < deadline) {
            var ok = false
            // Never query duration/position during MediaPlayer.prepareAsync: native
            // errors there are asynchronous and are not caught by runCatching.
            ui { ok = field("mediaPlayerPrepared") == true && runCatching(condition).getOrDefault(false) }
            if (ok) return
            SystemClock.sleep(100)
        }
        var detail = ""
        ui { detail = "normal=${field("normalPlayback")}, playing=${runCatching { player().isPlaying }}, position=${runCatching { player().currentPosition }}, track=${field("currentTrackInfo")}" }
        throw AssertionError("Timeout: $message ($detail)")
    }
    private fun test(name: String, block: () -> Unit) {
        count++
        try { block(); messages.append("PASS $name\n") }
        catch (e: Throwable) { failed++; messages.append("FAIL $name: ${e.stackTraceToString()}\n") }
        sendStatus(0, Bundle().apply { putString("stream", messages.lines().lastOrNull { it.startsWith("PASS ") || it.startsWith("FAIL ") }.orEmpty() + "\n") })
    }
    private fun capture(name: String) {
        // waitForIdleSync does not wait for SurfaceFlinger/rotation animations to finish.
        SystemClock.sleep(700)
        val image = uiAutomation.takeScreenshot() ?: error("No screenshot")
        val output = File(targetContext.getExternalFilesDir(null), "fullscreen-validation/$name.png")
        output.parentFile?.mkdirs()
        output.outputStream().use { image.compress(Bitmap.CompressFormat.PNG, 100, it) }
        image.recycle()
    }
    private fun find(view: View, description: String): View? {
        if (view.contentDescription?.toString() == description) return view
        if (view is ViewGroup) for (i in 0 until view.childCount) find(view.getChildAt(i), description)?.let { return it }
        return null
    }
    private fun click(description: String) = ui {
        val view = find(activity.window.decorView, description) ?: error("Missing $description")
        checkThat(view.isShown, "$description is hidden")
        view.performClick()
    }
    private fun dragCaption(dx: Float, dy: Float) = ui {
        val view = layout().caption
        val now = SystemClock.uptimeMillis()
        for ((action, delta) in listOf(MotionEvent.ACTION_DOWN to 0f, MotionEvent.ACTION_MOVE to 1f, MotionEvent.ACTION_UP to 1f)) {
            val event = MotionEvent.obtain(now, now + (delta * 100).toLong(), action, 20f + dx * delta, 20f + dy * delta, 0)
            view.onTouchEvent(event)
            event.recycle()
        }
    }
    private fun touch(x: Float, y: Float, double: Boolean = false) {
        repeat(if (double) 2 else 1) {
            val now = SystemClock.uptimeMillis()
            val down = MotionEvent.obtain(now, now, MotionEvent.ACTION_DOWN, x, y, 0)
            val up = MotionEvent.obtain(now, now + 30, MotionEvent.ACTION_UP, x, y, 0)
            down.source = android.view.InputDevice.SOURCE_TOUCHSCREEN
            up.source = android.view.InputDevice.SOURCE_TOUCHSCREEN
            // sendPointerSync waits for graphics transactions on every event; under video
            // rendering that can stretch two taps beyond Android's double-tap timeout.
            checkThat(uiAutomation.injectInputEvent(down, false), "DOWN injection failed")
            SystemClock.sleep(30)
            checkThat(uiAutomation.injectInputEvent(up, false), "UP injection failed")
            down.recycle(); up.recycle()
            if (double) SystemClock.sleep(40)
        }
        SystemClock.sleep(350)
    }
    private fun dragCaptionOnScreen(right: Boolean, bottom: Boolean) {
        var x = 0f; var y = 0f; var dx = 0f; var dy = 0f
        ui {
            val c = layout().caption
            val p = IntArray(2); c.getLocationOnScreen(p)
            x = p[0] + c.width / 2f; y = p[1] + c.height / 2f
            dx = (if (right) layout().width - 2f else 2f) - x
            dy = (if (bottom) layout().height - 2f else 2f) - y
        }
        val start = SystemClock.uptimeMillis()
        for (i in 0..12) {
            val action = when (i) { 0 -> MotionEvent.ACTION_DOWN; 12 -> MotionEvent.ACTION_UP; else -> MotionEvent.ACTION_MOVE }
            val event = MotionEvent.obtain(start, SystemClock.uptimeMillis(), action, x + dx * i / 12, y + dy * i / 12, 0)
            event.source = android.view.InputDevice.SOURCE_TOUCHSCREEN
            checkThat(uiAutomation.injectInputEvent(event, true), "Drag injection failed")
            event.recycle()
            SystemClock.sleep(20)
        }
        waitForIdleSync()
    }
    private fun touchWord() {
        var x = 0f; var y = 0f
        ui {
            val view = layout().caption
            val text = view.text as Spanned
            val span = text.getSpans(0, text.length, ClickableSpan::class.java).first()
            val offset = text.getSpanStart(span)
            val line = view.layout.getLineForOffset(offset)
            val location = IntArray(2); view.getLocationOnScreen(location)
            x = location[0] + view.totalPaddingLeft + view.layout.getPrimaryHorizontal(offset) + 8
            y = location[1] + view.totalPaddingTop + (view.layout.getLineTop(line) + view.layout.getLineBottom(line)) / 2f
        }
        touch(x, y)
    }
    private fun fullscreen(value: Boolean, portrait: Boolean = false) {
        ui { call("setFullscreen", value) }
        await("fullscreen layout") { layout().fullscreen == value && (!value || if (portrait) layout().width < layout().height else layout().width > layout().height) }
        SystemClock.sleep(500)
    }
    override fun onCreate(arguments: Bundle?) { super.onCreate(arguments); start() }
    override fun onStart() {
        try {
            activity = startActivitySync(Intent(targetContext, LearningActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as LearningActivity
            ui {
                set("pendingResumePositionMs", 0)
                call("loadVideo", android.net.Uri.parse("file:///sdcard/Download/Full Gear List for Solo Backpacking.mp4"), "Fullscreen validation", false, false)
            }
            await("video prepared") { player().duration > 1000 }
            ui {
                if (layout().fullscreen) call("setFullscreen", false)
                val lines = call("parseSrt", BufferedReader(StringReader("""
                    1
                    00:00:00,000 --> 00:00:30,000
                    This is my backpack for the trip.
                    这是我旅行用的背包。

                    2
                    00:00:35,000 --> 00:00:50,000
                    We are going to the mountains today.
                    我们今天要去山里。
                """.trimIndent()))) as List<*>
                @Suppress("UNCHECKED_CAST")
                val subtitles = field("subtitles") as MutableList<Any>
                subtitles.clear(); subtitles.addAll(lines.filterNotNull())
                set("selectedIndex", 0); set("normalPlayback", false); set("showCurrentTranslation", true)
                call("seekTo", 12000, false)
                call("renderSubtitles")
            }
            await("seek to 12 seconds") { abs(player().currentPosition - 12000) < 500 }
            test("inline_single_double_tap_hidden_controls_and_video_bound_progress") {
                var x = 0f; var y = 0f
                ui {
                    val controls = field("inlinePlayerControls") as InlinePlayerControls
                    controls.resetControls()
                    checkThat(!find(activity.window.decorView, "全屏播放")!!.isShown, "Inline fullscreen icon initially visible")
                    val location = IntArray(2); controls.getLocationOnScreen(location)
                    x = location[0] + controls.width / 2f; y = location[1] + controls.height * .3f
                }
                capture("09-inline-clean")
                touch(x, y)
                ui {
                    checkThat(!player().isPlaying, "Single tap started playback")
                    val controls = field("inlinePlayerControls") as InlinePlayerControls
                    val videoRect = android.graphics.Rect(); controls.getGlobalVisibleRect(videoRect)
                    for (description in listOf("全屏播放", "学习视频播放进度", "学习视频播放或暂停")) {
                        val view = find(activity.window.decorView, description)!!
                        val rect = android.graphics.Rect(); view.getGlobalVisibleRect(rect)
                        checkThat(view.isShown && videoRect.contains(rect), "$description outside video")
                    }
                }
                capture("10-inline-controls")
                touch(x, y, true)
                await("inline double tap starts") { player().isPlaying }
                SystemClock.sleep(3300)
                ui { checkThat(!find(activity.window.decorView, "全屏播放")!!.isShown, "Inline controls did not auto-hide") }
                ui {
                    val controls = field("inlinePlayerControls") as InlinePlayerControls
                    val location = IntArray(2); controls.getLocationOnScreen(location)
                    x = location[0] + controls.width / 2f; y = location[1] + controls.height * .3f
                }
                touch(x, y, true)
                await("inline double tap pauses") { !player().isPlaying }
                ui { checkThat(field("normalPlayback") == true, "Inline gesture failed to select continuous playback") }
                touch(x, y)
                ui { checkThat(!find(activity.window.decorView, "全屏播放")!!.isShown, "Inline single tap did not hide") }
                ui { call("seekTo", 12000, false) }
                await("inline reset position") { abs(player().currentPosition - 12000) < 500 }
            }
            test("same_player_surface_and_paused_position_across_rotation") {
                val original = field("mediaPlayer")
                val texture = field("textureView")
                repeat(3) {
                    fullscreen(true)
                    checkThat(field("mediaPlayer") === original, "Player was recreated")
                    checkThat(field("textureView") === texture, "TextureView was recreated")
                    ui { checkThat(!player().isPlaying && abs(player().currentPosition - 12000) < 500, "Paused position changed") }
                    fullscreen(false)
                }
            }
            test("inline_seek_and_fullscreen_entry_button") {
                ui { (field("inlinePlayerControls") as InlinePlayerControls).showControls() }
                click("全屏播放")
                await("inline entry opens fullscreen") { layout().fullscreen && layout().width > layout().height }
                SystemClock.sleep(600)
                click("退出全屏")
                await("exit returns portrait") { !layout().fullscreen && layout().height > layout().width }
                SystemClock.sleep(600)
                var x = 0f; var y = 0f
                ui {
                    checkThat(!find(activity.window.decorView, "全屏播放")!!.isShown, "Entry stayed visible on return")
                    (field("inlinePlayerControls") as InlinePlayerControls).showControls()
                    val seek = find(activity.window.decorView, "学习视频播放进度")!!
                    val location = IntArray(2); seek.getLocationOnScreen(location)
                    x = location[0] + seek.width / 2f; y = location[1] + seek.height / 2f
                }
                touch(x, y)
                await("inline seek midpoint") { abs(player().currentPosition - player().duration / 2) < 6000 }
                ui { checkThat(!player().isPlaying, "Inline seek started paused player") }
                ui { call("seekTo", 12000, false); set("selectedIndex", 0); set("normalPlayback", false); call("updateCurrentCaption") }
                await("inline seek reset") { abs(player().currentPosition - 12000) < 500 }
            }
            test("fullscreen_edge_chrome_and_previous_next_sentence") {
                fullscreen(true)
                ui {
                    val back = find(activity.window.decorView, "退出全屏")!!
                    val header = back.parent as View
                    checkThat(header.top == 0 && header.left == 0 && header.width == layout().width, "Header background inset from screen edges")
                    checkThat(layout().overlay.paddingTop == 0 && layout().overlay.paddingLeft == 0, "Entire overlay still inset")
                    val insets = androidx.core.view.ViewCompat.getRootWindowInsets(layout())!!
                    val visible = insets.getInsets(androidx.core.view.WindowInsetsCompat.Type.systemBars())
                    val cutout = insets.getInsetsIgnoringVisibility(androidx.core.view.WindowInsetsCompat.Type.displayCutout())
                    checkThat(back.top <= maxOf(visible.top, cutout.top) + (8 * activity.resources.displayMetrics.density).toInt(), "Back too far from safe top edge")
                }
                click("全屏下一句")
                await("next sentence") { field("selectedIndex") == 1 && abs(player().currentPosition - 35000) < 1600 }
                ui { player().pause(); checkThat(field("normalPlayback") == false, "Next lost sentence mode") }
                click("全屏上一句")
                await("previous sentence") { field("selectedIndex") == 0 && player().currentPosition < 1600 }
                ui { player().pause(); call("seekTo", 32000, false); set("selectedIndex", -1); call("updateCurrentCaption") }
                await("gap before next") { abs(player().currentPosition - 32000) < 500 }
                click("全屏下一句")
                await("next across gap") { field("selectedIndex") == 1 && abs(player().currentPosition - 35000) < 1600 }
                ui { player().pause(); call("seekTo", 32000, false); set("selectedIndex", -1); call("updateCurrentCaption") }
                await("gap before previous") { abs(player().currentPosition - 32000) < 500 }
                click("全屏上一句")
                await("previous across gap") { field("selectedIndex") == 0 && player().currentPosition < 1600 }
                ui { player().pause(); call("seekTo", 12000, false); set("selectedIndex", 0); call("updateCurrentCaption") }
                await("navigation reset") { abs(player().currentPosition - 12000) < 500 }
                capture("11-fullscreen-edge-controls")
            }
            test("current_sentence_translation_and_empty_gap_match_learning_page") {
                fullscreen(true)
                ui {
                    checkThat(layout().caption.text.toString() == (field("currentCaptionText") as TextView).text.toString(), "Caption mismatch")
                    checkThat(layout().caption.text.contains("背包"), "Translation missing")
                    set("showCurrentTranslation", false); call("updateCurrentCaption")
                    checkThat(!layout().caption.text.contains("背包"), "Translation off ignored")
                    set("selectedIndex", -1); call("updateCurrentCaption")
                    checkThat(layout().caption.visibility == View.GONE, "Stale caption in gap")
                    set("showCurrentTranslation", true); set("selectedIndex", 0); call("updateCurrentCaption")
                }
                capture("01-bilingual-controls")
            }
            test("fullscreen_subtitle_toggle_lock_current_sentence_and_gap") {
                click("字幕大小和位置设置")
                ui { if (!layout().caption.locked) find(activity.window.decorView, "锁定字幕位置和大小")!!.performClick() }
                var x = 0f; var y = 0f
                ui {
                    val button = find(activity.window.decorView, "关闭全屏字幕")!!
                    checkThat(button.isEnabled, "Subtitle lock disabled visibility switch")
                    val p = IntArray(2); button.getLocationOnScreen(p)
                    x = p[0] + button.width / 2f; y = p[1] + button.height / 2f
                }
                touch(x, y)
                ui {
                    checkThat(layout().caption.visibility == View.GONE, "Toggle did not hide caption")
                    checkThat(field("showCurrentTranslation") == true, "Toggle changed learning translation")
                }
                capture("12-subtitles-off")
                click("全屏下一句")
                await("hidden caption next sentence") { field("selectedIndex") == 1 && player().currentPosition >= 35000 }
                ui {
                    player().pause()
                    checkThat(layout().caption.visibility == View.GONE, "Next sentence made disabled caption visible")
                }
                click("开启全屏字幕")
                ui {
                    checkThat(layout().caption.isShown && layout().caption.text.contains("mountains"), "Enabling restored stale sentence")
                    checkThat(layout().caption.text.toString() == (field("currentCaptionText") as TextView).text.toString(), "Restored caption differs from learning page")
                }
                capture("13-subtitles-on-current-sentence")
                ui { call("seekTo", 32000, false); set("selectedIndex", -1); call("updateCurrentCaption") }
                await("gap for caption toggle") { abs(player().currentPosition - 32000) < 500 }
                click("关闭全屏字幕"); click("开启全屏字幕")
                ui { checkThat(layout().caption.visibility == View.GONE, "Enabling in gap shows stale caption") }
                ui { call("seekTo", 12000, false); set("selectedIndex", 0); call("updateCurrentCaption") }
                await("restore first sentence") { abs(player().currentPosition - 12000) < 500 }
                click("解锁字幕位置和大小")
                click("字幕大小和位置设置")
            }
            test("subtitle_drag_size_lock_and_reset") {
                click("字幕大小和位置设置")
                ui { if (layout().caption.locked) find(activity.window.decorView, "解锁字幕位置和大小")!!.performClick() }
                click("恢复字幕默认位置和大小")
                val before = layout().caption.position
                dragCaption(-100f, -160f)
                checkThat(layout().caption.position != before, "Caption did not move")
                ui { layout().showControls() }
                click("字幕大小和位置设置")
                val size = layout().caption.textSize
                click("放大字幕")
                checkThat(layout().caption.textSize > size, "Font did not increase")
                click("缩小字幕")
                checkThat(abs(layout().caption.textSize - size) < 1f, "Font did not decrease")
                click("放大字幕")
                click("锁定字幕位置和大小")
                val lockedPosition = layout().caption.position
                dragCaption(150f, 150f)
                checkThat(layout().caption.position == lockedPosition, "Locked caption moved")
                ui { checkThat(!find(activity.window.decorView, "放大字幕")!!.isEnabled, "Locked size still enabled") }
                capture("02-subtitle-locked")
                click("解锁字幕位置和大小")
                click("恢复字幕默认位置和大小")
                click("字幕大小和位置设置")
            }
            test("caption_reaches_all_safe_edges_without_chrome_repositioning") {
                ui { layout().overlay.performClick() }
                for ((right, bottom) in listOf(false to false, true to false, true to true, false to true)) {
                    dragCaptionOnScreen(right, bottom)
                    ui {
                        val c = layout().caption
                        val insets = androidx.core.view.ViewCompat.getRootWindowInsets(layout())!!
                        val bars = insets.getInsets(androidx.core.view.WindowInsetsCompat.Type.systemBars())
                        val cutout = insets.getInsetsIgnoringVisibility(androidx.core.view.WindowInsetsCompat.Type.displayCutout())
                        val margin = (4 * activity.resources.displayMetrics.density).toInt()
                        val edgeX = if (right) layout().width - maxOf(bars.right, cutout.right) - margin else maxOf(bars.left, cutout.left) + margin
                        val edgeY = if (bottom) layout().height - maxOf(bars.bottom, cutout.bottom) - margin else maxOf(bars.top, cutout.top) + margin
                        checkThat(abs((if (right) c.right else c.left) - edgeX) <= 2, "Horizontal edge unreachable")
                        checkThat(abs((if (bottom) c.bottom else c.top) - edgeY) <= 2, "Vertical edge unreachable")
                        checkThat(field("lookupDialogOpen") == false, "Drag opened dictionary")
                    }
                    capture("15-edge-${if (right) "right" else "left"}-${if (bottom) "bottom" else "top"}")
                }
                var bounds = android.graphics.Rect()
                ui { val c = layout().caption; bounds.set(c.left, c.top, c.right, c.bottom); layout().showControls() }
                click("字幕大小和位置设置")
                ui { val c = layout().caption; checkThat(bounds == android.graphics.Rect(c.left, c.top, c.right, c.bottom), "Settings moved caption") }
                click("恢复字幕默认位置和大小")
                click("字幕大小和位置设置")
            }
            test("navigation_alone_stops_once_even_with_loop_preference") {
                ui { set("loopSentence", true); call("seekTo", 12000, false) }
                await("before navigation") { abs(player().currentPosition - 12000) < 500 }
                click("全屏下一句")
                await("next started") { player().isPlaying && field("selectedIndex") == 1 }
                ui { call("seekTo", 49500, true) }
                await("next stops at sentence end") { !player().isPlaying && player().currentPosition >= 50000 }
                ui { checkThat(field("normalPlayback") == false, "Navigation unexpectedly continuous"); set("loopSentence", false) }
                capture("16-navigation-stopped-once")
            }
            test("play_after_sentence_end_continues_without_rewinding") {
                click("播放或暂停")
                await("continuous beyond selected sentence") { player().isPlaying && player().currentPosition > 51200 }
                ui { checkThat(field("normalPlayback") == true, "Play retained sentence boundary") }
                click("播放或暂停")
                await("continuous pause") { !player().isPlaying }
            }
            test("play_during_previous_sentence_continues_across_boundary") {
                ui { layout().showControls(); call("seekTo", 36000, false) }
                await("before previous") { abs(player().currentPosition - 36000) < 500 }
                click("全屏上一句")
                await("previous preview started") { player().isPlaying && field("selectedIndex") == 0 }
                ui { call("seekTo", 29000, true) }
                await("previous near end") { player().isPlaying && player().currentPosition >= 29000 }
                click("播放或暂停")
                await("play crosses first boundary") { player().isPlaying && player().currentPosition > 31200 }
                ui { checkThat(field("normalPlayback") == true, "Play paused active preview") }
                ui { player().pause(); layout().showControls() }
            }
            test("double_tap_during_next_sentence_continues_across_boundary") {
                click("全屏下一句")
                await("next preview for double tap") { player().isPlaying && field("selectedIndex") == 1 }
                ui { call("seekTo", 48000, true) }
                await("double tap near end") { player().isPlaying && player().currentPosition >= 48000 }
                touch(layout().width * .5f, layout().height * .35f, true)
                await("double tap crosses second boundary") { player().isPlaying && player().currentPosition > 51200 }
                ui { checkThat(field("normalPlayback") == true, "Double tap retained sentence mode") }
                capture("17-continuous-past-sentence")
                touch(layout().width * .5f, layout().height * .35f, true)
                await("double tap pauses continuous playback") { !player().isPlaying }
                ui { call("seekTo", 12000, false); set("selectedIndex", 0); call("updateCurrentCaption"); layout().showControls() }
                await("reset after continuous tests") { abs(player().currentPosition - 12000) < 500 }
            }
            test("playing_continues_controls_hide_and_word_lookup_pauses_resumes") {
                ui { set("normalPlayback", true); call("toggleFullscreenPlayback") }
                SystemClock.sleep(3700)
                ui {
                    checkThat(player().isPlaying && player().currentPosition > 13000, "Not playing")
                    checkThat(!find(activity.window.decorView, "退出全屏")!!.isShown, "Title/back did not auto-hide")
                    checkThat(layout().caption.isShown, "Caption hidden with controls")
                }
                capture("03-playing-subtitle-only")
                touchWord()
                ui { checkThat(field("lookupDialogOpen") == true && !player().isPlaying, "Actual word tap did not open dictionary/pause") }
                SystemClock.sleep(500)
                capture("04-dictionary")
                sendKeyDownUpSync(android.view.KeyEvent.KEYCODE_BACK)
                await("resume after lookup") { player().isPlaying }
                ui { player().pause() }
            }
            test("long_sentence_stays_inside_safe_area") {
                var originalLines = listOf<Any>()
                ui {
                    @Suppress("UNCHECKED_CAST") val subtitles = field("subtitles") as MutableList<Any>
                    originalLines = subtitles.toList()
                    val long = call("parseSrt", BufferedReader(StringReader("1\n00:00:00,000 --> 00:01:00,000\nI mean, I couldn't believe it, four thousand, five thousand, six thousand, and at that price, we couldn't even do our itinerary, rules, limitations.\n我是说，我简直不敢相信，而在那个价格下，我们甚至无法按自己的行程旅行。\n"))) as List<*>
                    subtitles.clear(); subtitles.addAll(long.filterNotNull()); set("selectedIndex", 0)
                    call("updateCurrentCaption")
                }
                waitForIdleSync()
                dragCaption(-10000f, -10000f)
                ui {
                    val c = layout().caption
                    checkThat(c.left >= c.travelBounds.left && c.top >= c.travelBounds.top, "Subtitle crossed top safe area")
                    checkThat(c.bottom <= layout().height && c.right <= layout().width, "Subtitle clipped")
                }
                capture("05-safe-area-long-caption")
                ui {
                    @Suppress("UNCHECKED_CAST") val subtitles = field("subtitles") as MutableList<Any>
                    subtitles.clear(); subtitles.addAll(originalLines); call("updateCurrentCaption"); layout().showControls()
                }
            }
            test("real_single_double_tap_and_locked_word_lookup") {
                click("字幕大小和位置设置")
                click("恢复字幕默认位置和大小")
                click("锁定字幕位置和大小")
                click("字幕大小和位置设置")
                var x = 0f; var y = 0f
                ui { x = layout().width * .5f; y = layout().height * .35f }
                touch(x, y)
                ui { checkThat(!find(activity.window.decorView, "退出全屏")!!.isShown, "Single tap did not hide") }
                touch(x, y)
                ui { checkThat(find(activity.window.decorView, "退出全屏")!!.isShown, "Single tap did not reveal") }
                touch(x, y, true)
                await("Double tap play") { player().isPlaying }
                touch(x, y, true)
                await("Double tap pause") { !player().isPlaying }
                touchWord()
                ui { checkThat(field("lookupDialogOpen") == true, "Locked subtitle could not look up word") }
                sendKeyDownUpSync(android.view.KeyEvent.KEYCODE_BACK)
                SystemClock.sleep(400)
                ui { checkThat(!player().isPlaying, "Paused lookup unexpectedly started playback") }
                capture("07-paused-locked-caption")
            }
            test("system_back_exits_fullscreen_without_finishing") {
                sendKeyDownUpSync(android.view.KeyEvent.KEYCODE_BACK)
                await("back exited fullscreen") { !layout().fullscreen }
                checkThat(!activity.isFinishing, "Back finished activity")
                SystemClock.sleep(700)
                capture("06-return-learning")
            }
            test("actual_seekbar_drag_preserves_pause_and_clears_caption_in_gap") {
                fullscreen(true)
                var x = 0f; var y = 0f
                ui {
                    layout().showControls()
                    val seek = find(activity.window.decorView, "全屏播放进度")!!
                    val location = IntArray(2); seek.getLocationOnScreen(location)
                    x = location[0] + seek.width / 2f; y = location[1] + seek.height / 2f
                }
                touch(x, y)
                await("seek to middle") { abs(player().currentPosition - player().duration / 2) < 6000 }
                ui {
                    checkThat(!player().isPlaying, "Seeking started paused video")
                    checkThat(layout().caption.visibility == View.GONE, "Seek into gap left stale caption")
                    call("seekTo", 12000, false); set("selectedIndex", 0); call("updateCurrentCaption")
                }
                await("return from seek") { abs(player().currentPosition - 12000) < 500 }
                fullscreen(false)
            }
            test("sentence_loop_and_offset_survive_fullscreen") {
                ui { set("normalPlayback", false); set("loopSentence", true); set("subtitleOffsetMs", 150); set("selectedIndex", 0) }
                fullscreen(true); fullscreen(false)
                checkThat(field("normalPlayback") == false && field("loopSentence") == true && field("subtitleOffsetMs") == 150 && field("selectedIndex") == 0, "Learning settings changed")
            }
            test("subtitle_settings_persist_after_page_rebuild") {
                ui { call("buildUi") }
                await("rebuilt player ready") { player().duration > 1000 }
                fullscreen(true)
                ui { checkThat(layout().caption.locked, "Subtitle lock not persisted") }
                click("字幕大小和位置设置")
                click("解锁字幕位置和大小")
                click("恢复字幕默认位置和大小")
                click("字幕大小和位置设置")
                fullscreen(false)
            }
            test("subtitle_visibility_persists_without_hiding_learning_caption") {
                fullscreen(true)
                click("字幕大小和位置设置"); click("关闭全屏字幕")
                fullscreen(false)
                ui { checkThat((field("currentCaptionText") as TextView).isShown, "Fullscreen switch hid learning caption") }
                fullscreen(true)
                ui { checkThat(layout().caption.visibility == View.GONE, "Re-enter reset visibility") }
                fullscreen(false)
                ui { call("buildUi") }
                await("player after visibility rebuild") { player().duration > 1000 }
                fullscreen(true)
                ui { checkThat(layout().caption.visibility == View.GONE, "Rebuild reset visibility preference") }
                click("字幕大小和位置设置"); click("开启全屏字幕")
                ui { checkThat(layout().caption.isShown, "Enable after rebuild failed") }
                click("字幕大小和位置设置")
                fullscreen(false)
            }
            test("background_pauses_and_return_does_not_autoplay") {
                fullscreen(true)
                ui { set("normalPlayback", true); player().start() }
                await("playing before Home") { player().isPlaying }
                sendKeyDownUpSync(android.view.KeyEvent.KEYCODE_HOME)
                await("Home paused player") { field("activityResumed") == false && !player().isPlaying }
                var pausedAt = 0
                ui { pausedAt = player().currentPosition }
                targetContext.startActivity(Intent(targetContext, LearningActivity::class.java)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_REORDER_TO_FRONT))
                await("returned to foreground") { field("activityResumed") == true }
                ui {
                    checkThat(!player().isPlaying && abs(player().currentPosition - pausedAt) < 500, "Background return changed pause/position")
                    checkThat(layout().fullscreen, "Background return lost fullscreen")
                }
                fullscreen(false)
            }
            test("portrait_video_fullscreen_and_return") {
                ui {
                    set("selectedIndex", -1); set("pendingResumePositionMs", 0); set("normalPlayback", true)
                    call("loadVideo", android.net.Uri.parse("file:///sdcard/Download/fullscreen-portrait-fixture.mp4"), "Portrait geometry fixture", false, false)
                }
                await("portrait media ready") { player().videoHeight > player().videoWidth && player().videoWidth > 0 }
                val original = field("mediaPlayer")
                fullscreen(true, portrait = true)
                ui {
                    checkThat(field("mediaPlayer") === original, "Portrait recreated player")
                    checkThat(activity.resources.configuration.orientation == android.content.res.Configuration.ORIENTATION_PORTRAIT, "Portrait video rotated sideways")
                }
                capture("08-portrait-video")
                click("字幕大小和位置设置")
                ui {
                    val screen = android.graphics.Rect(); layout().getGlobalVisibleRect(screen)
                    for (description in listOf("关闭全屏字幕", "缩小字幕", "放大字幕", "锁定字幕位置和大小", "恢复字幕默认位置和大小")) {
                        val button = find(activity.window.decorView, description)!!
                        val bounds = android.graphics.Rect(); button.getGlobalVisibleRect(bounds)
                        checkThat(button.isShown && bounds.width() == button.width && screen.contains(bounds), "Portrait subtitle setting clipped: $description")
                    }
                }
                capture("14-portrait-subtitle-settings")
                fullscreen(false)
                ui {
                    set("pendingResumePositionMs", 12000); set("selectedIndex", 0)
                    call("loadVideo", android.net.Uri.parse("file:///sdcard/Download/Full Gear List for Solo Backpacking.mp4"), "Fullscreen validation", false, false)
                }
                await("landscape restored") { player().videoWidth > player().videoHeight && player().videoHeight > 0 }
            }
        } catch (e: Throwable) { failed++; messages.append("SETUP FAILED ${e.stackTraceToString()}\n") }
        finish(if (failed == 0) Activity.RESULT_OK else Activity.RESULT_CANCELED, Bundle().apply {
            putString("stream", "\n$messages\nTests: $count, failures: $failed\n")
            putInt("failures", failed)
        })
    }
}
