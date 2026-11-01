package com.gathin.tvhome;

import android.content.Context;
import android.database.Cursor;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Handler;
import android.os.HandlerThread;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;

/**
 * Optional row of film posters under the last grid row (config.xml info_provider), filled from another app's content
 * provider. The launcher itself still has no network: the other app does the fetching and keeps the last value; this
 * only reads it, off the main thread, while Home is resumed. Off (the default): nothing is read or added to the screen.
 *
 * content://&lt;info_provider&gt;/cine answers "key", "titol", "sub" and "poster" (a content:// image); no rows, no
 * row on screen. Down from the grid's last row reaches it, and OK opens the provider app's film page (action
 * com.gathin.tvhome.action.SHOW_FILM, extra "key").
 */
final class InfoLine {

    static final long POLL_MS = 2 * 60 * 1000L;

    private final Context ctx;
    private final Handler main;
    private final FrameLayout root;
    private final View grid;
    private final String authority;
    private final Uri cineUri;
    private boolean atEnd;
    private Runnable cineUp;
    private View cinePanel;
    private LinearLayout cineRow;
    private volatile String cineShown;
    private HandlerThread thread;
    private volatile Handler bg;

    InfoLine(Context ctx, Handler main, FrameLayout root, View grid, String authority) {
        this.ctx = ctx;
        this.main = main;
        this.root = root;
        this.grid = grid;
        this.authority = authority == null || authority.trim().isEmpty() ? null : authority.trim();
        this.cineUri = this.authority == null ? null : Uri.parse("content://" + this.authority + "/cine");
        if (cineUri != null && grid instanceof androidx.recyclerview.widget.RecyclerView) {
            // RecyclerView moves its children rather than its own scroll position, so a ViewTreeObserver scroll
            // listener never hears it: follow its own scroll callbacks, and focus moves into or out of the posters.
            ((androidx.recyclerview.widget.RecyclerView) grid).addOnScrollListener(
                    new androidx.recyclerview.widget.RecyclerView.OnScrollListener() {
                        @Override
                        public void onScrolled(@androidx.annotation.NonNull androidx.recyclerview.widget.RecyclerView rv,
                                               int dx, int dy) {
                            updateScroll();
                        }
                    });
            root.getViewTreeObserver().addOnGlobalFocusChangeListener((oldFocus, newFocus) -> updateScroll());
        }
    }

    /** The posters show while the grid is at its end or while they hold the focus. */
    private void updateScroll() {
        androidx.recyclerview.widget.RecyclerView rv = (androidx.recyclerview.widget.RecyclerView) grid;
        androidx.recyclerview.widget.RecyclerView.LayoutManager lm = rv.getLayoutManager();
        androidx.recyclerview.widget.RecyclerView.Adapter<?> ad = rv.getAdapter();
        if (lm == null || ad == null) return;
        // Read the rows themselves (computeVerticalScrollOffset gave 0 here after focus moved back up): the grid
        // is scrolled down once the first row has left its resting place, and at its end once the last row sits
        // above the bottom padding, where the posters are.
        View first = lm.findViewByPosition(0);
        View last = ad.getItemCount() == 0 ? null : lm.findViewByPosition(ad.getItemCount() - 1);
        boolean inCine = cineRow != null && cineRow.hasFocus();
        boolean down = inCine || first == null || first.getTop() < rv.getPaddingTop() - dp(8);
        boolean end = inCine || (down && last != null
                && last.getBottom() <= rv.getHeight() - rv.getPaddingBottom() + dp(8));
        if (end != atEnd) {
            atEnd = end;
            if (cinePanel != null) cinePanel.animate().alpha(end ? 1f : 0f).setDuration(150).start();
        }
    }

    /** Up from the poster row: back to the grid's last row. */
    void setCineUp(Runnable up) {
        cineUp = up;
    }

    /** Down from the grid's last row: scroll the grid to its end, where the poster row shows, and focus it. */
    boolean focusCine() {
        if (cineRow == null || cineRow.getChildCount() == 0) return false;
        grid.scrollBy(0, dp(2000));   // to the end: the last row then sits just above the posters
        boolean focused = cineRow.getChildAt(0).requestFocus();
        updateScroll();
        return focused;
    }

    private static final String[] CINE_COLUMNS = {"key", "titol", "sub", "poster"};

    private java.util.List<String[]> readCine() {
        java.util.List<String[]> rows = new java.util.ArrayList<>();
        try (Cursor c = ctx.getContentResolver().query(cineUri, null, null, null, null)) {
            while (c != null && c.moveToNext() && rows.size() < 60) {
                String[] r = new String[CINE_COLUMNS.length];
                for (int i = 0; i < r.length; i++) {
                    int col = c.getColumnIndex(CINE_COLUMNS[i]);
                    r[i] = col < 0 || c.isNull(col) ? "" : c.getString(col);
                }
                rows.add(r);
            }
        } catch (RuntimeException ignored) {
            // no listings: the row stays hidden
        }
        return rows;
    }

    private static String cineKey(java.util.List<String[]> films) {
        StringBuilder key = new StringBuilder();
        for (String[] f : films) key.append(String.join("\u0001", f)).append('\u0002');
        return key.toString();
    }

    /** Each film's poster at tile size, in full colour (about 190 KB each); null where there is none. */
    private java.util.List<android.graphics.Bitmap> posters(java.util.List<String[]> films) {
        java.util.List<android.graphics.Bitmap> out = new java.util.ArrayList<>();
        int w = dp(POSTER_W), h = dp(POSTER_H);
        for (String[] f : films) {
            android.graphics.Bitmap b = null;
            if (!f[3].isEmpty()) {
                try (java.io.InputStream in = ctx.getContentResolver().openInputStream(Uri.parse(f[3]))) {
                    android.graphics.BitmapFactory.Options o = new android.graphics.BitmapFactory.Options();
                    o.inPreferredConfig = android.graphics.Bitmap.Config.ARGB_8888;   // RGB_565 banded the artwork
                    android.graphics.Bitmap full = android.graphics.BitmapFactory.decodeStream(in, null, o);
                    if (full != null) {
                        b = android.graphics.Bitmap.createScaledBitmap(full, w, h, true);
                        if (b != full) full.recycle();
                    }
                } catch (Exception ignored) {
                    // no poster: the title stands in
                }
            }
            out.add(b);
        }
        return out;
    }

    static final int POSTER_W = 88;
    static final int POSTER_H = 132;

    /**
     * The poster row at the very bottom, under the last grid row: "Cartellera" and up to 60 posters (about 90 KB each) with the title
     * and the next showing. It shows only while the grid is scrolled to its end (Down from the last row), and the
     * grid gets bottom padding so its last row stays clear of it. OK opens the provider app's film page.
     */
    private void showCine(java.util.List<String[]> films, java.util.List<android.graphics.Bitmap> posters, String key) {
        cineShown = key;
        View focusedFilm = cinePanel != null && cinePanel.hasFocus() ? cinePanel.findFocus() : null;
        Object focusedKey = focusedFilm == null ? null : focusedFilm.getTag();
        boolean hadFocus = focusedFilm != null;
        if (cinePanel != null) root.removeView(cinePanel);
        cinePanel = null;
        cineRow = null;
        int bottom = dp(40);
        if (!films.isEmpty()) {
            LinearLayout p = vertical();
            p.setBackground(glass());
            p.setPadding(dp(20), dp(12), dp(20), dp(10));
            TextView title = text("CARTELLERA · LA BISBAL, PALAFRUGELL, TORROELLA DE MONTGRÍ, PLATJA D'ARO, GIRONA i SALT",
                    12, 0xB3FFFFFF, true);
            title.setEllipsize(android.text.TextUtils.TruncateAt.END);
            title.setLetterSpacing(0.12f);
            p.addView(title);
            android.widget.HorizontalScrollView scroll = new android.widget.HorizontalScrollView(ctx);
            scroll.setHorizontalScrollBarEnabled(false);
            scroll.setClipChildren(false);
            scroll.setClipToPadding(false);
            cineRow = horizontal();
            cineRow.setGravity(Gravity.TOP);
            cineRow.setPadding(dp(6), dp(8), dp(6), dp(4));
            cineRow.setClipChildren(false);
            for (int i = 0; i < films.size(); i++) cineRow.addView(film(films.get(i), posters.get(i), i, films.size()));
            scroll.addView(cineRow);
            p.addView(scroll, new LinearLayout.LayoutParams(-1, -2));
            FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(-1, -2, Gravity.BOTTOM);
            lp.leftMargin = dp(56);
            lp.rightMargin = dp(56);
            lp.bottomMargin = dp(20);
            p.setAlpha(atEnd ? 1f : 0f);
            root.addView(p, lp);
            cinePanel = p;
            bottom = dp(POSTER_H + 130);   // the panel's height and margin, plus a gap above it
            if (hadFocus) {
                // The same film keeps focus across a refresh of the listings; if it left them, the first poster
                View same = focusedKey == null ? null : cineRow.findViewWithTag(focusedKey);
                (same != null ? same : cineRow.getChildAt(0)).requestFocus();
            }
        }
        if (grid.getPaddingBottom() != bottom) {
            grid.setPadding(grid.getPaddingLeft(), grid.getPaddingTop(), grid.getPaddingRight(), bottom);
        }
    }

    private View film(String[] f, android.graphics.Bitmap poster, int index, int count) {
        LinearLayout item = vertical();
        item.setTag(f[0]);   // the film's key, to find the poster again after a refresh or a film page
        item.setFocusable(true);
        item.setClickable(true);
        item.setPadding(dp(4), dp(4), dp(4), dp(4));
        android.widget.ImageView img = new android.widget.ImageView(ctx);
        img.setScaleType(android.widget.ImageView.ScaleType.CENTER_CROP);
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(0x33FFFFFF);
        bg.setCornerRadius(dp(10));
        img.setBackground(bg);
        img.setClipToOutline(true);
        if (poster != null) img.setImageBitmap(poster);
        item.addView(img, new LinearLayout.LayoutParams(dp(POSTER_W), dp(POSTER_H)));
        TextView name = text(f[1], 12, 0xFFFFFFFF, true);
        name.setEllipsize(android.text.TextUtils.TruncateAt.END);
        LinearLayout.LayoutParams ln = new LinearLayout.LayoutParams(dp(POSTER_W), -2);
        ln.topMargin = dp(6);
        item.addView(name, ln);
        TextView sub = text(f[2], 10, 0xB3FFFFFF, false);
        sub.setEllipsize(android.text.TextUtils.TruncateAt.END);
        LinearLayout.LayoutParams ls = new LinearLayout.LayoutParams(dp(POSTER_W), -2);
        ls.topMargin = dp(2);
        item.addView(sub, ls);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-2, -2);
        lp.rightMargin = dp(10);
        item.setLayoutParams(lp);
        item.setOnFocusChangeListener((v, focused) -> {
            GradientDrawable g = new GradientDrawable();
            g.setCornerRadius(dp(10));
            g.setColor(0x33FFFFFF);
            if (focused) g.setStroke(dp(2), 0xE6FFFFFF);
            img.setBackground(g);
            name.setEllipsize(focused ? android.text.TextUtils.TruncateAt.MARQUEE : android.text.TextUtils.TruncateAt.END);
            name.setSelected(focused);
            v.animate().scaleX(focused ? 1.06f : 1f).scaleY(focused ? 1.06f : 1f).setDuration(150).start();
        });
        item.setOnClickListener(v -> openFilm(f[0]));
        item.setOnKeyListener((v, keyCode, event) -> {
            if (event.getAction() != android.view.KeyEvent.ACTION_DOWN) return false;
            switch (keyCode) {
                case android.view.KeyEvent.KEYCODE_DPAD_UP:
                case android.view.KeyEvent.KEYCODE_BACK:
                case android.view.KeyEvent.KEYCODE_ESCAPE:
                    // Up and Back both return to the grid's last row
                    if (cineUp != null) cineUp.run();
                    return true;
                case android.view.KeyEvent.KEYCODE_DPAD_DOWN:
                    return true;
                // A carousel: Left from the first poster goes to the last one, Right from the last to the first
                case android.view.KeyEvent.KEYCODE_DPAD_LEFT:
                    if (index != 0 || cineRow == null) return false;
                    cineRow.getChildAt(count - 1).requestFocus();
                    return true;
                case android.view.KeyEvent.KEYCODE_DPAD_RIGHT:
                    if (index != count - 1 || cineRow == null) return false;
                    cineRow.getChildAt(0).requestFocus();
                    return true;
                default:
                    return false;
            }
        });
        return item;
    }

    /** The poster whose film page is open: focus goes back to it on the return to Home. */
    private String pendingFilm;

    /** Back on Home from a film page: focus that poster again (true), instead of the grid tile Home would restore. */
    boolean resumeCine() {
        String key = pendingFilm;
        pendingFilm = null;
        View item = key == null || cineRow == null ? null : cineRow.findViewWithTag(key);
        if (item == null) return false;
        grid.scrollBy(0, dp(2000));
        boolean focused = item.requestFocus();
        updateScroll();
        return focused;
    }

    void forgetFilm() {
        pendingFilm = null;
    }

    private void openFilm(String key) {
        pendingFilm = key;
        try {
            android.content.pm.ProviderInfo info = ctx.getPackageManager().resolveContentProvider(authority, 0);
            if (info == null) return;
            ctx.startActivity(new android.content.Intent("com.gathin.tvhome.action.SHOW_FILM")
                    .setPackage(info.packageName).putExtra("key", key)
                    .addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK));
        } catch (RuntimeException e) {
            android.widget.Toast.makeText(ctx, R.string.not_available, android.widget.Toast.LENGTH_SHORT).show();
        }
    }

    void start() {
        if (cineUri == null || thread != null) return;
        thread = new HandlerThread("info-line");
        thread.start();
        Handler h = new Handler(thread.getLooper());
        bg = h;
        h.post(new Runnable() {
            @Override
            public void run() {
                if (bg != h) return;
                java.util.List<String[]> films = readCine();
                String key = cineKey(films);
                java.util.List<android.graphics.Bitmap> posters = key.equals(cineShown) ? null : posters(films);
                main.post(() -> {
                    if (bg != h) return;
                    if (posters != null) showCine(films, posters, key);
                });
                if (bg == h) h.postDelayed(this, POLL_MS);
            }
        });
    }

    void stop() {
        if (thread == null) return;
        bg.removeCallbacksAndMessages(null);
        thread.quit();
        thread = null;
        bg = null;
        // The row stays on screen while paused, like show_stats.
    }

    /** Dark enough (75 %) to read over a bright wallpaper photo. */
    private GradientDrawable glass() {
        GradientDrawable g = new GradientDrawable();
        g.setColor(0xBF0C0E14);
        g.setStroke(dp(1), 0x40FFFFFF);
        g.setCornerRadius(dp(22));
        return g;
    }

    private LinearLayout vertical() {
        LinearLayout l = new LinearLayout(ctx);
        l.setOrientation(LinearLayout.VERTICAL);
        return l;
    }

    private LinearLayout horizontal() {
        LinearLayout l = new LinearLayout(ctx);
        l.setOrientation(LinearLayout.HORIZONTAL);
        l.setGravity(Gravity.CENTER_VERTICAL);
        return l;
    }

    private TextView text(String s, float sp, int color, boolean bold) {
        TextView t = new TextView(ctx);
        t.setText(s);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        t.setTextColor(color);
        t.setSingleLine(true);
        t.setIncludeFontPadding(false);
        if (bold) t.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        return t;
    }

    private int dp(int v) {
        return Math.round(v * ctx.getResources().getDisplayMetrics().density);
    }
}
