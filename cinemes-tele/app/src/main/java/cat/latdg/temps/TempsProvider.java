package cat.latdg.temps;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * La cartellera per al launcher: content://cat.latdg.temps/cine (la fila de pòsters), .../poster/<fitxer>.jpg (els
 * pòsters) i .../cine_estat (quan es va actualitzar i quines fonts van fallar).
 *
 * Respon sempre amb la darrera dada desada i, si cal, en baixa una de nova en un fil a part; el launcher la llegeix a
 * la consulta següent (cada 2 minuts mentre la pantalla d'inici és visible).
 */
public class TempsProvider extends ContentProvider {

    static final String[] DIES = {"Dg.", "Dl.", "Dt.", "Dc.", "Dj.", "Dv.", "Ds."};
    static final long VIGENCIA_CINE_MS = 3 * 60 * 60 * 1000L;
    /** Si l'última actualització va tenir algun error (una font que no respon), es torna a provar abans. */
    static final long VIGENCIA_CINE_ERRORS_MS = 10 * 60 * 1000L;
    private final AtomicBoolean baixantCine = new AtomicBoolean(false);
    private long darrerIntentCine;

    @Override
    public boolean onCreate() {
        return true;
    }

    @Override
    public Cursor query(Uri uri, String[] projection, String selection, String[] args, String sort) {
        if ("cine".equals(uri.getLastPathSegment())) return cine();
        if ("cine_estat".equals(uri.getLastPathSegment())) return cineEstat();
        return null;
    }

    /**
     * La cartellera per a la fila de pòsters del launcher: "key", "titol", "sub" (la propera sessió, o la data
     * d'estrena) i "poster" (content://cat.latdg.temps/poster/<fitxer>, o buit). Si cine.json té més de 3 hores (o
     * més de 10 minuts i alguna font hi va fallar), se'n baixa un de nou en un fil a part.
     */
    private Cursor cine() {
        MatrixCursor c = new MatrixCursor(new String[]{"key", "titol", "sub", "poster"});
        File f = new File(getContext().getFilesDir(), "cine.json");
        if (!f.exists()) {
            refrescaCine();
            return c;
        }
        try {
            long edat = System.currentTimeMillis() - f.lastModified();
            JSONObject desat = new JSONObject(new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8));
            JSONArray errors = desat.optJSONArray("errors");
            boolean ambErrors = errors != null && errors.length() > 0;
            if (edat > (ambErrors ? VIGENCIA_CINE_ERRORS_MS : VIGENCIA_CINE_MS)) refrescaCine();
            JSONArray films = desat.getJSONArray("films");
            java.util.Calendar ara = java.util.Calendar.getInstance();
            for (int i = 0; i < films.length(); i++) {
                JSONObject film = films.getJSONObject(i);
                String sub = propera(film, ara);
                if (sub == null) continue;   // les sessions ja han passat
                String poster = film.optString("poster");
                c.addRow(new String[]{film.optString("key"), film.optString("titol"), sub,
                        poster.isEmpty() ? "" : "content://cat.latdg.temps/poster/" + poster});
            }
        } catch (Exception ignored) {
            // sense files: el launcher amaga la fila
        }
        return c;
    }

    /** Per comprovar-ho des de l'ADB: quan es va actualitzar la cartellera i quines fonts van fallar. */
    private Cursor cineEstat() {
        MatrixCursor c = new MatrixCursor(new String[]{"actualitzat", "films", "errors"});
        try {
            JSONObject d = new JSONObject(new String(Files.readAllBytes(
                    new File(getContext().getFilesDir(), "cine.json").toPath()), StandardCharsets.UTF_8));
            c.addRow(new Object[]{new java.util.Date(d.optLong("actualitzat")).toString(),
                    d.getJSONArray("films").length(), d.optJSONArray("errors")});
        } catch (Exception e) {
            c.addRow(new Object[]{"", 0, e.toString()});
        }
        return c;
    }

    /** "Dg. 08.11.26 18.00 h · Teatre Mundial", "Dc. 28.10.26 21.30 h · 3 cinemes", "Estrena Dv. 06.11.26"; null si ja ha passat tot. */
    static String propera(JSONObject film, java.util.Calendar ara) {
        String avui = iso(ara);
        String horaAra = String.format(java.util.Locale.ROOT, "%02d:%02d", ara.get(java.util.Calendar.HOUR_OF_DAY),
                ara.get(java.util.Calendar.MINUTE));
        JSONArray ss = film.optJSONArray("sessions");
        if (ss == null || ss.length() == 0) {
            String e = film.optString("estrena");
            if (e.length() < 10) return null;
            return "Estrena " + dataCurta(e);
        }
        java.util.Set<String> cinemes = new java.util.TreeSet<>();
        JSONObject primera = null;
        for (int i = 0; i < ss.length(); i++) {
            JSONObject s = ss.optJSONObject(i);
            if (s == null) continue;
            String data = s.optString("data"), hora = s.optString("hora");
            if (data.compareTo(avui) < 0 || (data.equals(avui) && hora.compareTo(horaAra) < 0)) continue;
            cinemes.add(s.optString("cinema"));
            if (primera == null) primera = s;
        }
        if (primera == null) return null;
        String on = cinemes.size() == 1 ? primera.optString("cinema") : cinemes.size() + " cinemes";
        return dataCurta(primera.optString("data")) + " " + primera.optString("hora").replace(':', '.') + " h · " + on;
    }

    /** "2026-11-08" -> "Dg. 08.11.26": el format de tot el carrusel de la cartellera. */
    static String dataCurta(String iso) {
        return nomDia(iso) + " " + iso.substring(8, 10) + "." + iso.substring(5, 7) + "." + iso.substring(2, 4);
    }

    private void refrescaCine() {
        if (System.currentTimeMillis() - darrerIntentCine < 10 * 60 * 1000L) return;
        if (!baixantCine.compareAndSet(false, true)) return;
        darrerIntentCine = System.currentTimeMillis();
        File dir = getContext().getFilesDir();
        new Thread(() -> {
            try {
                Cinema.actualitza(dir);
            } catch (Exception ignored) {
                // es manté la darrera cartellera; es torna a provar d'aquí a 10 minuts
            } finally {
                baixantCine.set(false);
            }
        }, "cine").start();
    }

    /** Els pòsters de la cartellera: content://cat.latdg.temps/poster/<fitxer>.jpg */
    @Override
    public android.os.ParcelFileDescriptor openFile(Uri uri, String mode) throws java.io.FileNotFoundException {
        java.util.List<String> parts = uri.getPathSegments();
        if (parts.size() != 2 || !"poster".equals(parts.get(0)) || !parts.get(1).matches("[a-z0-9-]+\\.jpg")) {
            throw new java.io.FileNotFoundException(uri.toString());
        }
        File f = new File(new File(getContext().getFilesDir(), "posters"), parts.get(1));
        return android.os.ParcelFileDescriptor.open(f, android.os.ParcelFileDescriptor.MODE_READ_ONLY);
    }

    private static String iso(java.util.Calendar c) {
        return String.format(java.util.Locale.ROOT, "%04d-%02d-%02d", c.get(java.util.Calendar.YEAR),
                c.get(java.util.Calendar.MONTH) + 1, c.get(java.util.Calendar.DAY_OF_MONTH));
    }

    /** Nom curt del dia de la setmana per a una data AAAA-MM-DD. */
    static String nomDia(String iso) {
        java.util.Calendar c = java.util.Calendar.getInstance();
        c.clear();
        c.set(Integer.parseInt(iso.substring(0, 4)), Integer.parseInt(iso.substring(5, 7)) - 1,
                Integer.parseInt(iso.substring(8, 10)));
        return DIES[c.get(java.util.Calendar.DAY_OF_WEEK) - 1];
    }

    @Override public String getType(Uri uri) { return null; }
    @Override public Uri insert(Uri uri, ContentValues values) { return null; }
    @Override public int delete(Uri uri, String s, String[] a) { return 0; }
    @Override public int update(Uri uri, ContentValues v, String s, String[] a) { return 0; }
}
