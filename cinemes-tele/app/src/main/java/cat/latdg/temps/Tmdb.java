package cat.latdg.temps;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Calendar;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * La valoració i les plataformes d'una pel·lícula, de TMDB (themoviedb.org, ús personal no comercial; les
 * plataformes per a Espanya les dona JustWatch a través de TMDB). Sense token (BuildConfig.TMDB_TOKEN buit) no
 * fa res. Cada pel·lícula es consulta com a molt un cop al dia: els resultats es desen a tmdb.json.
 */
final class Tmdb {

    static final long VIGENCIA_MS = 24 * 60 * 60 * 1000L;
    static final String API = "https://api.themoviedb.org/3";

    /** Les apps de les plataformes a la TV, pel provider_id de TMDB; la resta es busquen a la Play Store. */
    static final Map<Integer, String[]> APPS = new LinkedHashMap<>();

    static {
        APPS.put(8, new String[]{"Netflix", "com.netflix.ninja"});
        APPS.put(1796, new String[]{"Netflix", "com.netflix.ninja"});
        APPS.put(175, new String[]{"Netflix", "com.netflix.ninja"});
        APPS.put(119, new String[]{"Prime Video", "com.amazon.amazonvideo.livingroom"});
        APPS.put(2100, new String[]{"Prime Video", "com.amazon.amazonvideo.livingroom"});
        APPS.put(337, new String[]{"Disney+", "com.disney.disneyplus"});
        APPS.put(1899, new String[]{"Max", "com.wbd.stream"});
        APPS.put(384, new String[]{"Max", "com.wbd.stream"});
        APPS.put(350, new String[]{"Apple TV+", "com.apple.atve.androidtv.appletv"});
        APPS.put(2, new String[]{"Apple TV+", "com.apple.atve.androidtv.appletv"});
    }

    private Tmdb() { }

    /** Afegeix "nota", "vots", "plataformes" (i la sinopsi o el pòster que faltin) a cada pel·lícula. */
    static void enriqueix(File dir, java.util.List<Cinema.Film> films) {
        String token = BuildConfig.TMDB_TOKEN;
        if (token == null || token.isEmpty()) return;
        File cache = new File(dir, "tmdb.json");
        JSONObject desat;
        try {
            desat = new JSONObject(new String(Files.readAllBytes(cache.toPath()), StandardCharsets.UTF_8));
        } catch (Exception e) {
            desat = new JSONObject();
        }
        JSONObject nou = new JSONObject();
        long ara = System.currentTimeMillis();
        for (Cinema.Film f : films) {
            JSONObject r = desat.optJSONObject(f.key);
            // v3: el pòster en català o castellà, i si la sinopsi és en castellà; les respostes d'abans es tornen a demanar
            if (r == null || ara - r.optLong("t") > VIGENCIA_MS || r.optInt("v") < 3) {
                try {
                    r = consulta(token, f);
                    r.put("t", ara).put("v", 3);
                } catch (Exception e) {
                    if (r == null) continue;   // sense xarxa: es fa servir la darrera resposta, si n'hi ha
                }
            }
            try {
                nou.put(f.key, r);
            } catch (Exception ignored) {
                // no passa
            }
            f.tmdb = r;
            if (f.sinopsi.isEmpty()) {
                f.sinopsi = r.optString("sinopsi");
                f.sinopsiEs = r.optBoolean("sinopsi_es");
            }
            // El pòster de TMDB (500 px) és més nítid que els dels cinemes: si n'hi ha, es fa servir aquest
            if (!r.optString("poster").isEmpty()) {
                f.posterJpeg = null;
                f.posterUrl = "https://image.tmdb.org/t/p/w500" + r.optString("poster");
            }
        }
        try (OutputStream o = new FileOutputStream(cache)) {
            o.write(nou.toString().getBytes(StandardCharsets.UTF_8));
        } catch (Exception ignored) {
            // la propera vegada es tornarà a consultar
        }
    }

    /** {"id", "nota", "vots", "sinopsi", "poster", "plataformes": [{"nom", "paquet"}]}; {} si no la troba. */
    static JSONObject consulta(String token, Cinema.Film f) throws Exception {
        JSONObject r = new JSONObject();
        JSONObject tria = cerca(token, f, "ca-ES");
        if (tria == null) tria = cerca(token, f, "es-ES");
        if (tria == null) return r;
        long id = tria.getLong("id");
        JSONObject d = get(token, API + "/movie/" + id + "?language=ca-ES&append_to_response=watch/providers");
        r.put("id", id);
        r.put("nota", d.optDouble("vote_average", 0));
        r.put("vots", d.optInt("vote_count", 0));
        String sinopsi = d.optString("overview");
        JSONObject castella = get(token, API + "/movie/" + id + "?language=es-ES");
        boolean sinopsiEs = sinopsi.isEmpty();
        if (sinopsiEs) sinopsi = castella.optString("overview");
        r.put("sinopsi_es", sinopsiEs && !sinopsi.isEmpty());
        r.put("sinopsi", sinopsi);
        r.put("poster", poster(token, id, d, castella));
        JSONArray plataformes = new JSONArray();
        java.util.Set<String> vistes = new java.util.HashSet<>();
        JSONObject es = d.optJSONObject("watch/providers") == null ? null
                : d.getJSONObject("watch/providers").optJSONObject("results");
        es = es == null ? null : es.optJSONObject("ES");
        for (String tipus : new String[]{"flatrate", "free", "ads"}) {
            JSONArray ps = es == null ? null : es.optJSONArray(tipus);
            for (int i = 0; ps != null && i < ps.length(); i++) {
                JSONObject p = ps.getJSONObject(i);
                String[] app = APPS.get(p.optInt("provider_id"));
                String nom = app != null ? app[0] : p.optString("provider_name")
                        .replaceAll("(?i)\\s+(standard with ads|with ads|amazon channel|basic)$", "").trim();
                if (nom.isEmpty() || !vistes.add(nom)) continue;
                plataformes.put(new JSONObject().put("nom", nom).put("paquet", app != null ? app[1] : ""));
            }
        }
        r.put("plataformes", plataformes);
        return r;
    }

    /**
     * El pòster en català si TMDB en té; si no, el de la versió en castellà (el dels cinemes d'aquí); i si tampoc,
     * el que TMDB dona per defecte (sovint l'original en anglès).
     */
    private static String poster(String token, long id, JSONObject catala, JSONObject castella) {
        try {
            JSONArray ps = get(token, API + "/movie/" + id + "/images?include_image_language=ca,es")
                    .optJSONArray("posters");
            for (String llengua : new String[]{"ca", "es"}) {
                for (int i = 0; ps != null && i < ps.length(); i++) {
                    JSONObject p = ps.getJSONObject(i);
                    if (llengua.equals(p.optString("iso_639_1"))) return p.optString("file_path");
                }
            }
        } catch (Exception ignored) {
            // sense la llista d'imatges: el pòster per defecte
        }
        String p = castella.optString("poster_path");
        if (p.isEmpty() || p.equals("null")) p = catala.optString("poster_path");
        return p.equals("null") ? "" : p;
    }

    /** El resultat de la cerca que millor s'hi assembla: mateix títol, l'any més proper a l'estrena, el més popular. */
    private static JSONObject cerca(String token, Cinema.Film f, String idioma) throws Exception {
        JSONArray res = get(token, API + "/search/movie?region=ES&language=" + idioma + "&query="
                + URLEncoder.encode(f.titol.replaceAll("\\([^)]*\\)", "").trim(), "UTF-8")).optJSONArray("results");
        if (res == null || res.length() == 0) return null;
        int anyRef = f.estrena.length() >= 4 ? Integer.parseInt(f.estrena.substring(0, 4))
                : Calendar.getInstance().get(Calendar.YEAR);
        JSONObject millor = null;
        double puntsMillor = -1e9;
        for (int i = 0; i < res.length(); i++) {
            JSONObject o = res.getJSONObject(i);
            boolean igual = Cinema.clau(o.optString("title")).equals(f.key)
                    || Cinema.clau(o.optString("original_title")).equals(f.key);
            String data = o.optString("release_date");
            int any = data.length() >= 4 ? Integer.parseInt(data.substring(0, 4)) : 0;
            double punts = (igual ? 1000 : 0) + Math.min(o.optDouble("popularity", 0), 200) / 10.0;
            if (any > 0 && !f.estrena.isEmpty()) punts -= Math.abs(any - anyRef) * 20;
            if (punts > puntsMillor) {
                puntsMillor = punts;
                millor = o;
            }
        }
        // Sense títol igual, només si és d'aquest any o del passat: si no, millor res que una altra pel·lícula
        if (millor != null && !Cinema.clau(millor.optString("title")).equals(f.key)
                && !Cinema.clau(millor.optString("original_title")).equals(f.key)) {
            String data = millor.optString("release_date");
            if (data.length() < 4 || Math.abs(Integer.parseInt(data.substring(0, 4)) - anyRef) > 1) return null;
        }
        return millor;
    }

    private static JSONObject get(String token, String url) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        c.setConnectTimeout(15000);
        c.setReadTimeout(20000);
        c.setRequestProperty("Authorization", "Bearer " + token);
        c.setRequestProperty("Accept", "application/json");
        try {
            if (c.getResponseCode() != 200) throw new Exception("TMDB HTTP " + c.getResponseCode());
            try (java.io.InputStream in = c.getInputStream()) {
                java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream();
                byte[] buf = new byte[8192];
                int n;
                while ((n = in.read(buf)) > 0) {
                    out.write(buf, 0, n);
                    if (out.size() > 1024 * 1024) throw new Exception("massa gran");
                }
                return new JSONObject(out.toString("UTF-8"));
            }
        } finally {
            c.disconnect();
        }
    }
}
