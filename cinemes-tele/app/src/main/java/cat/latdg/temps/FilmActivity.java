package cat.latdg.temps;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.text.TextUtils;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Calendar;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * La fitxa d'una pel·lícula de la cartellera: pòster, sinopsi, dades tècniques, la valoració i les plataformes
 * (si TMDB en té), i els passis de tots els cinemes que la fan, amb el preu quan el cinema el publica. S'obre
 * amb OK des d'un pòster del launcher (acció com.gathin.tvhome.action.SHOW_FILM, extra "key").
 */
public class FilmActivity extends Activity {

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        String key = getIntent().getStringExtra("key");
        JSONObject film = null;
        try {
            File f = new File(getFilesDir(), "cine.json");
            JSONArray films = new JSONObject(new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8))
                    .getJSONArray("films");
            for (int i = 0; i < films.length() && film == null; i++) {
                if (films.getJSONObject(i).optString("key").equals(key)) film = films.getJSONObject(i);
            }
        } catch (Exception ignored) {
            // sense dades: es tanca
        }
        if (film == null) {
            Toast.makeText(this, "Aquesta pel·lícula ja no és a la cartellera", Toast.LENGTH_LONG).show();
            finish();
            return;
        }

        LinearLayout arrel = new LinearLayout(this);
        arrel.setOrientation(LinearLayout.HORIZONTAL);
        arrel.setBackgroundColor(0xFF0B0D12);
        arrel.setPadding(dp(56), dp(36), dp(40), 0);
        setContentView(arrel);

        // Pòster
        ImageView poster = new ImageView(this);
        poster.setScaleType(ImageView.ScaleType.CENTER_CROP);
        GradientDrawable fonsPoster = new GradientDrawable();
        fonsPoster.setColor(0xFF1C1F27);
        fonsPoster.setCornerRadius(dp(14));
        poster.setBackground(fonsPoster);
        poster.setClipToOutline(true);
        String nomPoster = film.optString("poster");
        if (!nomPoster.isEmpty()) {
            Bitmap bm = BitmapFactory.decodeFile(new File(new File(getFilesDir(), "posters"), nomPoster).getPath());
            if (bm != null) poster.setImageBitmap(bm);
        }
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(dp(220), dp(330));
        lp.rightMargin = dp(36);
        arrel.addView(poster, lp);

        // Fitxa
        ScrollView scroll = new ScrollView(this);
        scroll.setVerticalScrollBarEnabled(false);
        LinearLayout fitxa = new LinearLayout(this);
        fitxa.setOrientation(LinearLayout.VERTICAL);
        fitxa.setPadding(0, 0, dp(16), dp(40));
        scroll.addView(fitxa, new ViewGroup.LayoutParams(-1, -2));
        arrel.addView(scroll, new LinearLayout.LayoutParams(0, -1, 1f));

        TextView titol = text(film.optString("titol"), 30, Color.WHITE, true);
        titol.setSingleLine(false);
        fitxa.addView(titol);

        StringBuilder meta = new StringBuilder();
        afegeix(meta, film.optString("genere"));
        if (!film.optString("durada").isEmpty()) afegeix(meta, film.optString("durada") + " min");
        afegeix(meta, film.optString("edat"));
        String estrena = film.optString("estrena");
        if (estrena.length() >= 10) afegeix(meta, "Estrena " + data(estrena, false));
        if (meta.length() > 0) fitxa.addView(text(meta.toString(), 16, 0xB3FFFFFF, false), marge(6));

        // Valoració i plataformes (TMDB)
        double nota = film.optDouble("nota", -1);
        if (nota > 0) {
            String estrelles = estrelles(nota);
            String vots = film.optInt("vots", 0) > 0 ? "  ·  " + film.optInt("vots") + " vots" : "";
            fitxa.addView(text(estrelles + "  " + String.format(java.util.Locale.ROOT, "%.1f", nota).replace('.', ',')
                    + " / 10" + vots + "  ·  TMDB", 17, 0xFFFFD166, true), marge(10));
        }
        JSONArray plataformes = film.optJSONArray("plataformes");
        if (plataformes != null && plataformes.length() > 0) {
            fitxa.addView(text("TAMBÉ A", 12, 0x99FFFFFF, true), marge(14));
            LinearLayout fila = new LinearLayout(this);
            fila.setOrientation(LinearLayout.HORIZONTAL);
            for (int i = 0; i < plataformes.length(); i++) {
                JSONObject p = plataformes.optJSONObject(i);
                if (p == null) continue;
                View boto = botoPlataforma(p, film.optString("titol"));
                LinearLayout.LayoutParams lb = new LinearLayout.LayoutParams(-2, -2);
                lb.rightMargin = dp(12);
                fila.addView(boto, lb);
            }
            fitxa.addView(fila, marge(6));
        }

        String sinopsi = film.optString("sinopsi");
        if (!sinopsi.isEmpty()) {
            TextView t = text(sinopsi, 17, 0xE6FFFFFF, false);
            t.setSingleLine(false);
            t.setLineSpacing(0, 1.2f);
            fitxa.addView(t, marge(16));
        }
        String director = film.optString("director"), actors = film.optString("actors");
        if (!director.isEmpty()) fitxa.addView(dada("Direcció", director), marge(12));
        if (!actors.isEmpty()) fitxa.addView(dada("Repartiment", actors), marge(4));

        // Passis, per cinema i per dia
        Map<String, Map<String, StringBuilder>> perCinema = new LinkedHashMap<>();
        Map<String, String> preus = new LinkedHashMap<>();
        JSONArray ss = film.optJSONArray("sessions");
        Calendar ara = Calendar.getInstance();
        String avui = Cinema.iso(ara);
        String horaAra = String.format(java.util.Locale.ROOT, "%02d:%02d", ara.get(Calendar.HOUR_OF_DAY),
                ara.get(Calendar.MINUTE));
        for (int i = 0; ss != null && i < ss.length(); i++) {
            JSONObject s = ss.optJSONObject(i);
            if (s == null) continue;
            String d = s.optString("data"), h = s.optString("hora");
            if (d.compareTo(avui) < 0 || (d.equals(avui) && h.compareTo(horaAra) < 0)) continue;
            String cinema = s.optString("cinema");
            Map<String, StringBuilder> dies = perCinema.computeIfAbsent(cinema, k -> new LinkedHashMap<>());
            StringBuilder hores = dies.computeIfAbsent(d, k -> new StringBuilder());
            if (hores.length() > 0) hores.append("   ");
            hores.append(h.replace(':', '.'));   // 22.00, com a l'agenda
            if (!s.optString("format").isEmpty()) hores.append(" (").append(s.optString("format")).append(")");
            if (!s.optString("preu").isEmpty()) preus.put(cinema, s.optString("preu"));
        }
        View primer = null;
        if (perCinema.isEmpty()) {
            fitxa.addView(text(estrena.length() >= 10 ? "Encara sense sessions. S'estrena el " + data(estrena, true) + "."
                    : "No hi ha més sessions programades.", 17, 0xB3FFFFFF, false), marge(24));
        } else {
            fitxa.addView(text("SESSIONS", 13, 0x99FFFFFF, true), marge(24));
        }
        for (Map.Entry<String, Map<String, StringBuilder>> e : perCinema.entrySet()) {
            LinearLayout targeta = targeta();
            String cap = e.getKey() + (preus.containsKey(e.getKey()) ? "  ·  " + preus.get(e.getKey()) : "");
            targeta.addView(text(cap, 18, 0xFFFF6F61, true));
            for (Map.Entry<String, StringBuilder> dia : e.getValue().entrySet()) {
                LinearLayout fila = new LinearLayout(this);
                fila.setOrientation(LinearLayout.HORIZONTAL);
                TextView quin = text(data(dia.getKey(), false), 16, 0xB3FFFFFF, false);
                fila.addView(quin, new LinearLayout.LayoutParams(dp(170), -2));
                TextView hores = text(dia.getValue().toString(), 16, Color.WHITE, true);
                hores.setSingleLine(false);
                fila.addView(hores, new LinearLayout.LayoutParams(0, -2, 1f));
                LinearLayout.LayoutParams lf = new LinearLayout.LayoutParams(-1, -2);
                lf.topMargin = dp(6);
                targeta.addView(fila, lf);
            }
            fitxa.addView(targeta, marge(10));
            if (primer == null) primer = targeta;
        }
        if (primer != null) {
            TextView peu = text("Preus d'Odeon i OCINE a la seva web o a la taquilla.", 13, 0x80FFFFFF, false);
            fitxa.addView(peu, marge(14));
        }
        // Atribució que demana TMDB (themoviedb.org/about/logos-attribution)
        // La frase oficial ha d'anar en anglès; a sobre, la traducció
        TextView tmdb = text("Valoracions i plataformes: TMDB i JustWatch.\n\nAquest producte fa servir l'API de TMDB, "
                + "però TMDB no l'avala ni el certifica.", 13, 0x99FFFFFF, false);
        tmdb.setSingleLine(false);
        fitxa.addView(tmdb, marge(primer != null ? 10 : 20));
        TextView oficial = text("This product uses the TMDB API but is not endorsed or certified by TMDB.", 11,
                0x66FFFFFF, false);
        oficial.setSingleLine(false);
        fitxa.addView(oficial, marge(4));
        View focus = primer;
        if (plataformes != null && plataformes.length() > 0) focus = null;   // el primer botó agafa el focus sol
        if (focus != null) focus.requestFocus();
        scroll.post(() -> scroll.scrollTo(0, 0));   // el títol a dalt, encara que el focus sigui més avall
    }

    /** Botó d'una plataforma: obre la seva app a la TV (o la seva web al navegador si no hi és). */
    private View botoPlataforma(JSONObject p, String titol) {
        TextView t = text(p.optString("nom"), 16, Color.WHITE, true);
        t.setGravity(Gravity.CENTER);
        t.setPadding(dp(18), dp(8), dp(18), dp(8));
        t.setFocusable(true);
        t.setClickable(true);
        t.setBackground(fons(false, true));
        t.setOnFocusChangeListener((v, f) -> v.setBackground(fons(f, true)));
        t.setOnClickListener(v -> {
            String paquet = p.optString("paquet");
            Intent i = paquet.isEmpty() ? null : getPackageManager().getLeanbackLaunchIntentForPackage(paquet);
            if (i == null && !paquet.isEmpty()) i = getPackageManager().getLaunchIntentForPackage(paquet);
            if (i == null) {
                // No és a la TV: la Play Store, a la fitxa de l'app o buscant-la pel nom
                Intent botiga = new Intent(Intent.ACTION_VIEW, android.net.Uri.parse(paquet.isEmpty()
                        ? "market://search?q=" + android.net.Uri.encode(p.optString("nom")) + "&c=apps"
                        : "market://details?id=" + paquet));
                Toast.makeText(this, p.optString("nom") + " no és a la TV: pots instal·lar-la des de la Play Store",
                        Toast.LENGTH_LONG).show();
                try {
                    startActivity(botiga.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
                } catch (RuntimeException e) {
                    Toast.makeText(this, "No s'ha pogut obrir la Play Store", Toast.LENGTH_LONG).show();
                }
                return;
            }
            Toast.makeText(this, "Busca «" + titol + "» a " + p.optString("nom"), Toast.LENGTH_LONG).show();
            startActivity(i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        });
        return t;
    }

    /** 0..10 -> de 0 a 5 estrelles senceres (la font de la TV no té mitja estrella; la nota exacta va al costat). */
    static String estrelles(double nota) {
        int plenes = (int) Math.round(nota / 2);
        StringBuilder b = new StringBuilder();
        for (int i = 0; i < 5; i++) b.append(i < plenes ? "★" : "☆");
        return b.toString();
    }

    /** "2026-10-28" -> "Dc. 28.10.2026" (o "Avui", "Demà"); llarg: "dimecres 28.10.2026". */
    private String data(String iso, boolean llarg) {
        Calendar ara = Calendar.getInstance();
        if (!llarg && iso.equals(Cinema.iso(ara))) return "Avui";
        ara.add(Calendar.DAY_OF_MONTH, 1);
        if (!llarg && iso.equals(Cinema.iso(ara))) return "Demà";
        // Com a l'agenda i a les fonts: 28.10.2026
        String dia = iso.substring(8, 10) + "." + iso.substring(5, 7) + "." + iso.substring(0, 4);
        if (llarg) {
            Calendar c = Calendar.getInstance();
            c.clear();
            c.set(Integer.parseInt(iso.substring(0, 4)), Integer.parseInt(iso.substring(5, 7)) - 1,
                    Integer.parseInt(iso.substring(8, 10)));
            return Cinema.DIES_CAT[c.get(Calendar.DAY_OF_WEEK) - 1] + " " + dia;
        }
        return TempsProvider.nomDia(iso.substring(0, 10)) + " " + dia;
    }

    private LinearLayout targeta() {
        LinearLayout t = new LinearLayout(this);
        t.setOrientation(LinearLayout.VERTICAL);
        t.setFocusable(true);
        t.setPadding(dp(20), dp(12), dp(20), dp(14));
        t.setBackground(fons(false, false));
        t.setOnFocusChangeListener((v, f) -> v.setBackground(fons(f, false)));
        return t;
    }

    private GradientDrawable fons(boolean focus, boolean boto) {
        GradientDrawable g = new GradientDrawable();
        g.setCornerRadius(dp(boto ? 22 : 16));
        g.setColor(focus ? 0xFF262A33 : boto ? 0xFF1E2230 : 0xFF161920);
        if (focus) g.setStroke(dp(2), 0xE6FFFFFF);
        return g;
    }

    private View dada(String nom, String valor) {
        TextView t = text(nom + ": " + valor, 15, 0xB3FFFFFF, false);
        t.setSingleLine(false);
        t.setMaxLines(2);
        t.setEllipsize(TextUtils.TruncateAt.END);
        return t;
    }

    private static void afegeix(StringBuilder b, String s) {
        if (s == null || s.trim().isEmpty()) return;
        if (b.length() > 0) b.append("  ·  ");
        b.append(s.trim());
    }

    private LinearLayout.LayoutParams marge(int dalt) {
        LinearLayout.LayoutParams l = new LinearLayout.LayoutParams(-1, -2);
        l.topMargin = dp(dalt);
        return l;
    }

    private TextView text(String s, float sp, int color, boolean negreta) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        t.setTextColor(color);
        if (negreta) t.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        return t;
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }
}
