package cat.latdg.temps;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.util.Base64;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.text.Normalizer;
import java.util.ArrayList;
import java.util.Calendar;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * La cartellera dels cinemes de les comarques de Girona, en una sola llista de pel·lícules: cada pel·lícula
 * una vegada, amb les sessions de tots els cinemes que la fan.
 *
 * Fonts (les mateixes que mostren les seves webs, sense comprar ni reservar res):
 *  - OCINE Girona i OCINE Platja d'Aro: l'API pública de la seva web d'entrades (llista i fitxa de cada pel·lícula).
 *  - Cinema Montgrí (Torroella): la portada (sessions) i la fitxa de cada pel·lícula.
 *  - Teatre Mundial (la Bisbal) i TeMePé (Palafrugell): l'agenda municipal, amb les dades schema.org de cada
 *    sessió i el preu.
 *  - Odeon Girona (Salt): la pàgina de pel·lícules, que porta totes les sessions. La seva web rebutja els
 *    lectors que no són un navegador (HTTP 403), així que es llegeix a través de Jina Reader (r.jina.ai), amb un
 *    User-Agent que diu qui és (Jina rebutja els que es fan passar per un navegador). Una vegada cada 3 hores com a
 *    molt (10 minuts després d'un error). Si falla, es mantenen les darreres sessions bones (recupera()).
 * Una font que falla no atura les altres. El resultat es desa a cine.json i els pòsters a posters/.
 */
final class Cinema {

    static final String UA = "Mozilla/5.0 (Linux; Android 10; MiTV) AppleWebKit/537.36 (KHTML, like Gecko) "
            + "Chrome/120.0 Safari/537.36";
    static final int DIES_ENDAVANT = 30;
    static final int MAX_PROPERES = 8;
    static final int POSTER_W = 500;

    static final class Sessio {
        String cinema, data, hora, format = "", preu = "";
    }

    static final class Film {
        String key, titol, sinopsi = "", durada = "", genere = "", edat = "", director = "", actors = "",
                estrena = "", any = "", posterUrl = "", web = "";
        byte[] posterJpeg;
        int qualitatText;   // 2 = català (OCINE, Montgrí, agendes), 1 = castellà (Odeon)
        JSONObject tmdb;    // valoració i plataformes (Tmdb.enriqueix); null sense token o sense resultat
        String posterNom;   // recupera(): el pòster que ja tenia a la cartellera anterior
        boolean sinopsiEs, genereEs, edatEs;   // textos que han arribat en castellà: Traductor els passa al català
        final List<Sessio> sessions = new ArrayList<>();
    }

    private Cinema() { }

    // ---------------------------------------------------------------- tot plegat

    /** Baixa totes les fonts, les fusiona i desa cine.json i els pòsters a dir. Retorna el nombre de pel·lícules. */
    static int actualitza(File dir) throws Exception {
        Map<String, Film> films = new LinkedHashMap<>();
        List<String> errors = new ArrayList<>();
        java.util.Set<String> fallats = new java.util.HashSet<>();   // els cinemes de les fonts que han fallat
        Calendar ara = Calendar.getInstance();
        String[][] ocines = {{"https://tickets.ocinegirona.es", "OCINE Girona"},
                {"https://tickets.ocineplatjadaro.es", "OCINE Platja d'Aro"}};
        for (String[] o : ocines) {
            try {
                ocine(o[0], o[1], films);
            } catch (Exception e) {
                errors.add(o[1] + ": " + e);
                fallats.add(o[1]);
            }
        }
        try {
            odeon(films);
        } catch (Exception e) {
            errors.add("Odeon: " + e);
            fallats.add("Odeon Girona");
        }
        try {
            montgri(films, ara);
        } catch (Exception e) {
            errors.add("Montgrí: " + e);
            fallats.add("Cinema Montgrí");
        }
        try {
            agendaMunicipal("https://www.teatremundial.cat", "1000", "Teatre Mundial", films);
        } catch (Exception e) {
            errors.add("Mundial: " + e);
            fallats.add("Teatre Mundial");
        }
        try {
            agendaMunicipal("https://cultura.palafrugell.cat", "18", "TeMePé Palafrugell", films);
        } catch (Exception e) {
            errors.add("Palafrugell: " + e);
            fallats.add("TeMePé Palafrugell");
        }
        if (!fallats.isEmpty()) {
            try {
                recupera(new File(dir, "cine.json"), fallats, films);
            } catch (Exception ignored) {
                // sense cartellera anterior: aquests cinemes no surten fins que tornin a respondre
            }
        }
        if (films.isEmpty()) throw new Exception("cap font: " + errors);

        String avui = iso(ara);
        Calendar fi = (Calendar) ara.clone();
        fi.add(Calendar.DAY_OF_MONTH, DIES_ENDAVANT);
        String darrer = iso(fi);
        File posters = new File(dir, "posters");
        //noinspection ResultOfMethodCallIgnored
        posters.mkdirs();

        JSONArray llista = new JSONArray();
        List<Film> ambSessions = new ArrayList<>(), properes = new ArrayList<>();
        for (Film f : films.values()) {
            f.sessions.removeIf(s -> s.data.compareTo(avui) < 0 || s.data.compareTo(darrer) > 0);
            f.sessions.sort((a, b) -> (a.data + a.hora + a.cinema).compareTo(b.data + b.hora + b.cinema));
            if (!f.sessions.isEmpty()) ambSessions.add(f);
            else if (f.estrena.compareTo(avui) > 0) properes.add(f);
        }
        // Primer el que es pot veure abans (la propera sessió); a igualtat de dia, l'estrena més recent
        String horaAra = String.format(Locale.ROOT, "%02d:%02d", ara.get(Calendar.HOUR_OF_DAY), ara.get(Calendar.MINUTE));
        ambSessions.removeIf(f -> propera(f, avui, horaAra) == null);
        ambSessions.sort((a, b) -> {
            Sessio pa = propera(a, avui, horaAra), pb = propera(b, avui, horaAra);
            int d = pa.data.compareTo(pb.data);
            return d != 0 ? d : b.estrena.compareTo(a.estrena);
        });
        properes.sort((a, b) -> a.estrena.compareTo(b.estrena));
        if (properes.size() > MAX_PROPERES) properes = properes.subList(0, MAX_PROPERES);
        List<Film> tots = new ArrayList<>(ambSessions);
        tots.addAll(properes);

        Tmdb.enriqueix(dir, tots);
        // Tot en català: el que només ha arribat en castellà es tradueix (una vegada; queda desat)
        Traductor traductor = new Traductor(dir);
        for (Film f : tots) {
            if (f.sinopsiEs) f.sinopsi = traductor.tradueix(f.sinopsi);
            if (f.genereEs) f.genere = frase(traductor.tradueix(f.genere));
            if (f.edatEs) f.edat = frase(traductor.tradueix(f.edat));
        }
        traductor.desa();
        java.util.Set<String> posterNoms = new java.util.HashSet<>();
        for (Film f : tots) {
            // El nom porta una empremta de l'origen del pòster: si canvia (un altre pòster de TMDB), es baixa de nou
            String origen = !f.posterUrl.isEmpty() ? f.posterUrl : f.posterJpeg != null ? "jpeg" + f.posterJpeg.length : "";
            String nom = origen.isEmpty() && f.posterNom != null && !f.posterNom.isEmpty() ? f.posterNom
                    : f.key.replaceAll("[^a-z0-9]+", "-") + "-" + Integer.toHexString(origen.hashCode()) + ".jpg";
            File p = new File(posters, nom);
            if (!p.exists() || System.currentTimeMillis() - p.lastModified() > 7L * 24 * 3600 * 1000) {
                try {
                    desaPoster(f, p);
                } catch (Exception ignored) {
                    // sense pòster: el launcher mostra el títol
                }
            }
            if (p.exists()) posterNoms.add(nom);
            llista.put(json(f, p.exists() ? nom : ""));
        }
        File[] vells = posters.listFiles();
        if (vells != null) for (File v : vells) if (!posterNoms.contains(v.getName())) //noinspection ResultOfMethodCallIgnored
            v.delete();

        JSONObject out = new JSONObject();
        out.put("actualitzat", System.currentTimeMillis());
        out.put("errors", new JSONArray(errors));
        out.put("films", llista);
        File tmp = new File(dir, "cine.json.tmp");
        try (OutputStream o = new FileOutputStream(tmp)) {
            o.write(out.toString().getBytes(StandardCharsets.UTF_8));
        }
        //noinspection ResultOfMethodCallIgnored
        tmp.renameTo(new File(dir, "cine.json"));
        return tots.size();
    }

    /**
     * La memòria cau d'un cinema que no ha respost (per exemple, des d'una VPN): les seves sessions de la cartellera
     * anterior es tornen a afegir, amb la fitxa de la pel·lícula, perquè no desapareguin. Si ha fallat algun OCINE,
     * també es conserven les estrenes anunciades (encara sense sessions), que surten d'OCINE.
     */
    private static void recupera(File anterior, java.util.Set<String> fallats, Map<String, Film> films) throws Exception {
        JSONArray vells = new JSONObject(new String(java.nio.file.Files.readAllBytes(anterior.toPath()),
                StandardCharsets.UTF_8)).getJSONArray("films");
        boolean ocine = fallats.contains("OCINE Girona") || fallats.contains("OCINE Platja d'Aro");
        for (int i = 0; i < vells.length(); i++) {
            JSONObject v = vells.getJSONObject(i);
            JSONArray ss = v.optJSONArray("sessions");
            List<Sessio> recuperades = new ArrayList<>();
            for (int k = 0; ss != null && k < ss.length(); k++) {
                JSONObject s = ss.getJSONObject(k);
                if (!fallats.contains(s.optString("cinema"))) continue;
                Sessio x = new Sessio();
                x.cinema = s.optString("cinema");
                x.data = s.optString("data");
                x.hora = s.optString("hora");
                x.format = s.optString("format");
                x.preu = s.optString("preu");
                recuperades.add(x);
            }
            boolean estrena = ocine && (ss == null || ss.length() == 0);
            if (recuperades.isEmpty() && !estrena) continue;
            Film f = film(films, v.optString("titol"));
            // 2: el que es va desar ja era en català (traduït si calia)
            completa(f, 2, v.optString("titol"), v.optString("sinopsi"), v.optString("durada"), v.optString("genere"),
                    v.optString("edat"), v.optString("director"), v.optString("actors"), v.optString("estrena"));
            if (f.web.isEmpty()) f.web = v.optString("web");
            if (f.posterNom == null) f.posterNom = v.optString("poster");
            f.sessions.addAll(recuperades);
        }
    }

    /** La primera sessió que encara no ha començat; null si ja han passat totes. */
    private static Sessio propera(Film f, String avui, String horaAra) {
        for (Sessio s : f.sessions) {
            if (s.data.compareTo(avui) > 0 || (s.data.equals(avui) && s.hora.compareTo(horaAra) >= 0)) return s;
        }
        return null;
    }

    private static JSONObject json(Film f, String poster) throws Exception {
        JSONObject j = new JSONObject();
        j.put("key", f.key).put("titol", f.titol).put("sinopsi", f.sinopsi).put("durada", f.durada)
                .put("genere", f.genere).put("edat", f.edat).put("director", f.director).put("actors", f.actors)
                .put("estrena", f.estrena).put("any", f.any).put("poster", poster).put("web", f.web);
        JSONArray ss = new JSONArray();
        for (Sessio s : f.sessions) {
            ss.put(new JSONObject().put("cinema", s.cinema).put("data", s.data).put("hora", s.hora)
                    .put("format", s.format).put("preu", s.preu));
        }
        j.put("sessions", ss);
        if (f.tmdb != null && f.tmdb.has("id")) {
            j.put("nota", f.tmdb.optDouble("nota", 0)).put("vots", f.tmdb.optInt("vots", 0))
                    .put("plataformes", f.tmdb.optJSONArray("plataformes"));
        }
        return j;
    }

    /** El pòster a 500 px d'amplada com a molt (la fitxa el mostra a uns 440), en JPEG. */
    private static void desaPoster(Film f, File desti) throws Exception {
        byte[] dades = f.posterJpeg;
        if (dades == null && !f.posterUrl.isEmpty()) dades = baixaBytes(f.posterUrl, 4 * 1024 * 1024);
        if (dades == null) return;
        BitmapFactory.Options o = new BitmapFactory.Options();
        o.inJustDecodeBounds = true;
        BitmapFactory.decodeByteArray(dades, 0, dades.length, o);
        int mostra = 1;
        while (o.outWidth / (mostra * 2) >= POSTER_W) mostra *= 2;
        o = new BitmapFactory.Options();
        o.inSampleSize = mostra;
        Bitmap b = BitmapFactory.decodeByteArray(dades, 0, dades.length, o);
        if (b == null) return;
        if (b.getWidth() > POSTER_W) {
            Bitmap r = Bitmap.createScaledBitmap(b, POSTER_W, Math.round(b.getHeight() * (float) POSTER_W / b.getWidth()), true);
            if (r != b) b.recycle();
            b = r;
        }
        File tmp = new File(desti.getPath() + ".tmp");
        try (OutputStream out = new FileOutputStream(tmp)) {
            b.compress(Bitmap.CompressFormat.JPEG, 90, out);
        } finally {
            b.recycle();
        }
        //noinspection ResultOfMethodCallIgnored
        tmp.renameTo(desti);
    }

    // ---------------------------------------------------------------- fusió

    /** La pel·lícula d'aquest títol, nova o la que ja hi era d'un altre cinema. */
    static Film film(Map<String, Film> films, String titol) {
        String key = clau(titol);
        Film f = films.get(key);
        if (f == null) {
            f = new Film();
            f.key = key;
            f.titol = titol.trim();
            films.put(key, f);
        }
        return f;
    }

    /** Omple els camps buits de f; amb qualitat més alta (text en català), també substitueix els textos. */
    static void completa(Film f, int qualitat, String titol, String sinopsi, String durada, String genere,
                         String edat, String director, String actors, String estrena) {
        boolean millor = qualitat > f.qualitatText;
        if (millor && !titol.isEmpty()) f.titol = titol.trim();
        if (!sinopsi.isEmpty() && (millor || f.sinopsi.isEmpty())) f.sinopsi = sinopsi.trim();
        if (!genere.isEmpty() && (millor || f.genere.isEmpty())) {
            f.genere = genere.trim();
            f.genereEs = qualitat == 1;   // l'Odeon escriu en castellà
        }
        if (!edat.isEmpty() && (millor || f.edat.isEmpty())) {
            f.edat = edat.trim();
            f.edatEs = qualitat == 1;
        }
        if (f.durada.isEmpty() && !durada.isEmpty()) f.durada = durada.replaceAll("\\D", "");
        if (f.director.isEmpty()) f.director = director.trim();
        if (f.actors.isEmpty()) f.actors = actors.trim();
        if (f.estrena.isEmpty() && estrena.matches("\\d{4}-\\d{2}-\\d{2}.*")) f.estrena = estrena.substring(0, 10);
        if (millor) f.qualitatText = qualitat;
    }

    /** "Cars (20 Aniversario)", "CARS (REESTRENO)", "Cinema. Cars" -> "cars". */
    static String clau(String titol) {
        String t = Normalizer.normalize(titol.toLowerCase(Locale.ROOT), Normalizer.Form.NFD)
                .replaceAll("\\p{M}", "");
        t = t.replaceAll("^cinema\\.\\s*", "");
        t = t.replaceAll("\\([^)]*\\)|\\[[^]]*]", " ");
        t = t.replaceAll("\\b(v\\.?o\\.?s\\.?e\\.?|vose|vosc|vos|v\\.?o\\.?|3d|4d|atmos|imax)\\b", " ");
        t = t.replaceAll("[^a-z0-9]+", " ").trim();
        return t.isEmpty() ? titol.toLowerCase(Locale.ROOT) : t;
    }

    // ---------------------------------------------------------------- OCINE

    static void ocine(String base, String nom, Map<String, Film> films) throws Exception {
        String cos = new JSONObject().put("token", "").put("idioma", "ca")
                .put("urlWeb", base + "/?idioma=ca&nocap=1").toString();
        JSONObject d = new JSONObject(baixa(base + "/api/v1/sessions", cos, 6 * 1024 * 1024));
        JSONArray pelis = d.optJSONArray("pelicules");
        for (int i = 0; pelis != null && i < pelis.length(); i++) {
            JSONObject p = pelis.getJSONObject(i);
            JSONObject fitxa;
            try {
                fitxa = new JSONObject(baixa(base + "/api/v1/pelicula/" + p.getLong("id") + "?lang=ca", null,
                        2 * 1024 * 1024));
            } catch (Exception e) {
                fitxa = p;
            }
            Film f = film(films, fitxa.optString("titol", p.optString("titol")));
            ocineDades(f, fitxa);
            if (f.web.isEmpty()) f.web = base + "/?idioma=ca";
            afegeixSessions(f, nom, fitxa.optJSONArray("sessions"), "");
            JSONArray subs = fitxa.optJSONArray("subPelicules");
            for (int k = 0; subs != null && k < subs.length(); k++) {
                JSONObject s = subs.getJSONObject(k);
                afegeixSessions(f, nom, s.optJSONArray("sessions"), formatOcine(s.optJSONArray("propietatsDesc")));
            }
        }
        // Estrenes properes: encara sense sessions, només la data
        JSONArray estrenes = d.optJSONArray("estrenes");
        for (int i = 0; estrenes != null && i < estrenes.length(); i++) {
            JSONObject p = estrenes.getJSONObject(i);
            Film f = film(films, p.optString("titol"));
            ocineDades(f, p);
        }
    }

    private static void ocineDades(Film f, JSONObject p) {
        StringBuilder actors = new StringBuilder();
        for (String k : new String[]{"actor1", "actriu1", "actor2", "actriu2"}) {
            String a = p.optString(k).trim();
            if (!a.isEmpty()) actors.append(actors.length() > 0 ? ", " : "").append(a);
        }
        completa(f, 2, p.optString("titol"), p.optString("sinopsis").replace("\r", ""), p.optString("durada"),
                p.optString("genereComercial"), p.optString("classificacio"), p.optString("director"),
                actors.toString(), p.optString("dataEstrena"));
        String b64 = p.optString("poster");
        if (f.posterJpeg == null && b64.length() > 1000) {
            try {
                f.posterJpeg = Base64.decode(b64, Base64.DEFAULT);
            } catch (IllegalArgumentException ignored) {
                // pòster il·legible
            }
        }
    }

    private static String formatOcine(JSONArray desc) {
        StringBuilder b = new StringBuilder();
        for (int i = 0; desc != null && i < desc.length(); i++) {
            String d = desc.optString(i).trim();
            if (d.isEmpty() || d.equalsIgnoreCase("Estàndar") || d.equalsIgnoreCase("2D")
                    || d.equalsIgnoreCase("Digital")) continue;
            b.append(b.length() > 0 ? " " : "").append(d.replace("Sala ", ""));
        }
        return b.toString();
    }

    private static void afegeixSessions(Film f, String cinema, JSONArray ss, String format) {
        for (int i = 0; ss != null && i < ss.length(); i++) {
            JSONObject s = ss.optJSONObject(i);
            if (s == null) continue;
            Sessio x = new Sessio();
            x.cinema = cinema;
            x.data = s.optString("data");
            String h = s.optString("hora");
            x.hora = h.length() >= 5 ? h.substring(0, 5) : h;
            x.format = format;
            if (x.data.matches("\\d{4}-\\d{2}-\\d{2}")) f.sessions.add(x);
        }
    }

    // ---------------------------------------------------------------- Odeon

    static final String ODEON = "https://odeonmulticines.com/odeon-girona/peliculas";
    static final String JINA = "https://r.jina.ai/";
    static final Pattern ODEON_DIA = Pattern.compile("<div class=\"day-(\\d{4}-\\d{2}-\\d{2})");
    static final Pattern ODEON_HORA = Pattern.compile("data-time=\"(\\d{2})(\\d{2})\"");

    static void odeon(Map<String, Film> films) throws Exception {
        String html = baixa(JINA + ODEON, null, 4 * 1024 * 1024);
        String[] blocs = html.split("<div class=\"show-\\d+ ");
        if (blocs.length < 2) throw new Exception("pàgina sense pel·lícules");
        for (int i = 1; i < blocs.length; i++) {
            String b = blocs[i];
            String titol = titolCas(text(primer(b, "<h5>(.*?)</h5>")).replaceAll("\\(\\s+", "(")
                    .replaceAll("\\s+\\)", ")"));
            if (titol.isEmpty()) continue;
            Film f = film(films, titol);
            completa(f, 1, titol, "", primer(b, "<span>(\\d+) min</span>"),
                    text(primer(b, "genre-icon2?\\.png\"\\s*>\\s*<span>(.*?)</span>")),
                    text(primer(b, "class=\"me-3 cal-icon\" alt=\"([^\"]*)\"")), "", "", "");
            if (f.posterUrl.isEmpty()) {
                String p = primer(b, "src=\"(https://cdn\\.odeonmulticines\\.com/show-posters/[^\"?]+)");
                if (!p.isEmpty()) f.posterUrl = p + "?width=500";
            }
            if (f.web.isEmpty()) f.web = "https://odeonmulticines.com/odeon-girona";
            for (String dia : b.split("(?=<div class=\"day-\\d{4}-\\d{2}-\\d{2})")) {
                Matcher md = ODEON_DIA.matcher(dia);
                if (!md.lookingAt()) continue;
                String format = formatOdeon(primer(dia, "data-format=\"([^\"]*)\""));
                Matcher mh = ODEON_HORA.matcher(dia);
                while (mh.find()) {
                    Sessio s = new Sessio();
                    s.cinema = "Odeon Girona";
                    s.data = md.group(1);
                    s.hora = mh.group(1) + ":" + mh.group(2);
                    s.format = format;
                    f.sessions.add(s);
                }
            }
        }
    }

    private static String formatOdeon(String f) {
        StringBuilder b = new StringBuilder();
        for (String p : f.split("\\s+")) {
            if (p.isEmpty() || p.equals("2D") || p.equals("DIGITAL")) continue;
            // ATMOS -> Atmos, INFINITY -> Infinity; 3D, 4D i VOSE es queden en majúscules
            if (!p.matches("\\dD|VOSE|VO")) p = p.charAt(0) + p.substring(1).toLowerCase(Locale.ROOT);
            b.append(b.length() > 0 ? " " : "").append(p);
        }
        return b.toString();
    }

    // ---------------------------------------------------------------- Cinema Montgrí

    static final Pattern MONTGRI_FILM = Pattern.compile(
            "<h2><a href=\"(https://cinemamontgri\\.cat/[^\"]+)\">(.*?)</a></h2>\\s*<ul class=\"session-list\">(.*?)</ul>",
            Pattern.DOTALL);
    static final Pattern MONTGRI_SESSIO = Pattern.compile(
            "<li>\\s*(\\p{L}+)\\s+(\\d{1,2})\\s*·\\s*(\\d{1,2})[.:](\\d{2})\\s*(?:\\(([^)]*)\\))?");

    static void montgri(Map<String, Film> films, Calendar ara) throws Exception {
        String html = baixa("https://cinemamontgri.cat/", null, 2 * 1024 * 1024);
        Map<String, String> fets = new HashMap<>();
        Matcher m = MONTGRI_FILM.matcher(html);
        while (m.find()) {
            String url = m.group(1), titol = text(m.group(2));
            if (titol.isEmpty()) continue;
            Film f = film(films, titol);
            boolean nou = !fets.containsKey(url);
            fets.put(url, titol);
            java.util.Set<String> vistes = new java.util.HashSet<>();
            for (Sessio s : f.sessions) if (s.cinema.equals("Cinema Montgrí")) vistes.add(s.data + s.hora);
            Matcher ms = MONTGRI_SESSIO.matcher(m.group(3));
            while (ms.find()) {
                String data = dataPerDia(ara, ms.group(1), Integer.parseInt(ms.group(2)));
                if (data == null) continue;
                Sessio s = new Sessio();
                s.cinema = "Cinema Montgrí";
                s.data = data;
                s.hora = String.format(Locale.ROOT, "%02d:%s", Integer.parseInt(ms.group(3)), ms.group(4));
                s.format = ms.group(5) == null ? "" : ms.group(5);
                if (vistes.add(s.data + s.hora)) f.sessions.add(s);
            }
            if (nou) {
                if (f.web.isEmpty()) f.web = url;
                try {
                    montgriFitxa(f, url);
                } catch (Exception ignored) {
                    // sense fitxa: només el títol i les sessions
                }
            }
        }
    }

    private static void montgriFitxa(Film f, String url) throws Exception {
        String html = baixa(url, null, 2 * 1024 * 1024);
        String cos = text(html.replaceAll("(?s)<script.*?</script>|<style.*?</style>", "")
                .replaceAll("<(?:/p|br|/h\\d|/li|/div|/dt|/dd)[^>]*>", "\n"));
        String sinopsi = primer(html, "<meta property=\"og:description\" content=\"([^\"]*)\"");
        completa(f, 2, "", text(sinopsi), camp(cos, "Durada"), camp(cos, "Gènere"), "", camp(cos, "Direcció"),
                camp(cos, "Repartiment"), "");
        if (f.posterUrl.isEmpty() && f.posterJpeg == null) {
            f.posterUrl = primer(html, "<meta property=\"og:image\" content=\"([^\"]*)\"");
        }
    }

    /** El camp d'una fitxa: la línia que segueix "Durada", "Direcció", etc. */
    private static String camp(String text, String nom) {
        Matcher m = Pattern.compile("(?m)^\\s*" + Pattern.quote(nom) + "\\s*:?\\s*\\n\\s*(.+)$").matcher(text);
        return m.find() ? m.group(1).trim() : "";
    }

    static final String[] DIES_CAT = {"diumenge", "dilluns", "dimarts", "dimecres", "dijous", "divendres", "dissabte"};

    /** "Dissabte", 7 -> la data AAAA-MM-DD del proper dissabte dia 7 (o d'ahir), dins dels propers 60 dies. */
    static String dataPerDia(Calendar ara, String nomDia, int dia) {
        String nd = nomDia.toLowerCase(Locale.ROOT);
        Calendar c = (Calendar) ara.clone();
        c.add(Calendar.DAY_OF_MONTH, -1);
        for (int i = 0; i < 62; i++) {
            if (c.get(Calendar.DAY_OF_MONTH) == dia && DIES_CAT[c.get(Calendar.DAY_OF_WEEK) - 1].equals(nd)) return iso(c);
            c.add(Calendar.DAY_OF_MONTH, 1);
        }
        return null;
    }

    // ---------------------------------------------------------------- agendes municipals (Mundial, Palafrugell)

    static final Pattern LD = Pattern.compile("<script[^>]*application/ld\\+json[^>]*>(.*?)</script>", Pattern.DOTALL);

    static void agendaMunicipal(String base, String categoria, String nom, Map<String, Film> films) throws Exception {
        String llista = baixa(base + "/ca/programacio.html?ordre=data_propera_funcio&filtre_categories%5B%5D="
                + categoria + "&filtre_historic=0", null, 2 * 1024 * 1024);
        java.util.Set<String> urls = new java.util.LinkedHashSet<>();
        Matcher m = Pattern.compile("href=\"(" + Pattern.quote(base) + "/ca/programacio/c/\\d+-[^\"]+\\.html)\"")
                .matcher(llista);
        while (m.find() && urls.size() < 30) urls.add(m.group(1));
        for (String url : urls) {
            try {
                agendaFitxa(url, nom, films);
            } catch (Exception ignored) {
                // una fitxa que falla no atura les altres
            }
        }
    }

    private static void agendaFitxa(String url, String nom, Map<String, Film> films) throws Exception {
        String html = baixa(url, null, 2 * 1024 * 1024);
        String titol = "", sinopsi = "", imatge = "", preu = "";
        List<String[]> sessions = new ArrayList<>();
        Matcher m = LD.matcher(html);
        while (m.find()) {
            Object arrel;
            try {
                arrel = new org.json.JSONTokener(m.group(1).trim()).nextValue();
            } catch (Exception e) {
                continue;
            }
            JSONArray items = arrel instanceof JSONArray ? (JSONArray) arrel : new JSONArray().put(arrel);
            for (int i = 0; i < items.length(); i++) {
                JSONObject o = items.optJSONObject(i);
                if (o == null) continue;
                String tipus = o.optString("@type");
                if (tipus.equals("Event")) {
                    if (titol.isEmpty()) titol = o.optString("name");
                    if (sinopsi.isEmpty()) sinopsi = o.optString("description");
                    if (imatge.isEmpty()) imatge = o.optString("image");
                    String inici = o.optString("startDate");
                    if (inici.matches("\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}.*")) {
                        sessions.add(new String[]{inici.substring(0, 10), inici.substring(11, 16)});
                    }
                } else if (tipus.equals("Product") && preu.isEmpty()) {
                    JSONObject oferta = o.optJSONObject("offers");
                    if (oferta != null && oferta.has("price")) {
                        double p = oferta.optDouble("price", -1);
                        if (p == 0) preu = "Gratuït";
                        else if (p > 0) preu = (p == Math.floor(p) ? String.valueOf((long) p)
                                : String.format(Locale.ROOT, "%.2f", p).replace('.', ',')) + " €";
                    }
                }
            }
        }
        if (titol.isEmpty() || sessions.isEmpty()) return;
        titol = titolCas(titol.replaceFirst("^(?i)cinema\\.\\s*", ""));
        Film f = film(films, titol);
        String cos = text(html.replaceAll("(?s)<script.*?</script>|<style.*?</style>", "")
                .replaceAll("<(?:/p|br|/h\\d|/li|/div|/dt|/dd)[^>]*>", "\n"));
        String durada = primer(cos, "Durada:\\s*(\\d+)");
        String director = primer(cos, "Direcció:\\s*([^\\n]+)");
        String genere = primer(cos, "Gènere:\\s*([^\\n]+)");
        String edat = primer(cos, "Qualificació:\\s*([^\\n]+)");
        String actors = primer(cos, "Intèrprets:\\s*([^\\n]+)");
        completa(f, 2, titol, sinopsi, durada, genere, edat, director, actors, "");
        if (f.posterUrl.isEmpty() && f.posterJpeg == null && !imatge.isEmpty()) f.posterUrl = imatge;
        if (f.web.isEmpty()) f.web = url;
        for (String[] s : sessions) {
            Sessio x = new Sessio();
            x.cinema = nom;
            x.data = s[0];
            x.hora = s[1];
            x.preu = preu;
            boolean ja = false;
            for (Sessio y : f.sessions) ja |= y.cinema.equals(nom) && y.data.equals(x.data) && y.hora.equals(x.hora);
            if (!ja) f.sessions.add(x);
        }
    }

    // ---------------------------------------------------------------- utilitats

    /** "No Recomanada per a Menors de 7 anys" -> "No recomanada per a menors de 7 anys" (l'Odeon ho capitalitza tot). */
    static String frase(String s) {
        if (s == null || s.length() < 2) return s;
        return s.substring(0, 1).toUpperCase(Locale.ROOT) + s.substring(1).toLowerCase(Locale.ROOT);
    }

    /** "BALANDRAU" -> "Balandrau"; un títol amb minúscules es deixa com és. */
    static String titolCas(String t) {
        t = t.trim();
        if (!t.equals(t.toUpperCase(Locale.ROOT))) return t;
        StringBuilder b = new StringBuilder(t.toLowerCase(Locale.ROOT));
        boolean inici = true;
        for (int i = 0; i < b.length(); i++) {
            char c = b.charAt(i);
            if (inici && Character.isLetter(c)) {
                b.setCharAt(i, Character.toUpperCase(c));
                inici = false;
            } else if (c == '.' || c == ':' || c == '-') {
                inici = true;
            }
        }
        return b.toString();
    }

    static String primer(String s, String regex) {
        Matcher m = Pattern.compile(regex, Pattern.DOTALL).matcher(s);
        return m.find() ? m.group(1).trim() : "";
    }

    /** Treu les etiquetes HTML i desfà les entitats més habituals. */
    static String text(String html) {
        String t = html.replaceAll("<[^>]+>", "");
        t = t.replace("&nbsp;", " ").replace("&amp;", "&").replace("&quot;", "\"").replace("&#039;", "'")
                .replace("&#39;", "'").replace("&#8217;", "’").replace("&rsquo;", "’").replace("&#8211;", "–")
                .replace("&lt;", "<").replace("&gt;", ">").replace("&#038;", "&").replace("&middot;", "·");
        Matcher m = Pattern.compile("&#(\\d+);").matcher(t);
        StringBuffer b = new StringBuffer();
        while (m.find()) m.appendReplacement(b, Matcher.quoteReplacement(
                new String(Character.toChars(Integer.parseInt(m.group(1))))));
        m.appendTail(b);
        return b.toString().replaceAll("[ \\t\\x0B\\f\\r]+", " ").replaceAll(" *\\n[ \\n]*", "\n").trim();
    }

    static String iso(Calendar c) {
        return String.format(Locale.ROOT, "%04d-%02d-%02d", c.get(Calendar.YEAR), c.get(Calendar.MONTH) + 1,
                c.get(Calendar.DAY_OF_MONTH));
    }

    static String baixa(String url, String cosJson, int max) throws Exception {
        return new String(baixaBytes(url, cosJson, max), StandardCharsets.UTF_8);
    }

    static byte[] baixaBytes(String url, int max) throws Exception {
        return baixaBytes(url, null, max);
    }

    /** GET (o POST amb cos JSON) amb un límit de mida; segueix les redireccions https. */
    static byte[] baixaBytes(String url, String cosJson, int max) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        if (c instanceof javax.net.ssl.HttpsURLConnection && url.contains(".ocine")) {
            // El servidor d'entrades d'OCINE talla la salutació TLS 1.3 d'Android 10; en TLS 1.2 respon bé
            ((javax.net.ssl.HttpsURLConnection) c).setSSLSocketFactory(Tls12.factoria());
        }
        c.setConnectTimeout(15000);
        c.setReadTimeout(30000);
        if (url.startsWith(JINA)) {
            c.setRequestProperty("User-Agent", "LaTdG-TV/1.0 (cartellera personal)");
            c.setRequestProperty("X-Return-Format", "html");
        } else {
            c.setRequestProperty("User-Agent", UA);
            c.setRequestProperty("Accept-Language", "ca,es;q=0.8");
        }
        try {
            if (cosJson != null) {
                c.setRequestMethod("POST");
                c.setDoOutput(true);
                c.setRequestProperty("Content-Type", "application/json");
                try (OutputStream o = c.getOutputStream()) {
                    o.write(cosJson.getBytes(StandardCharsets.UTF_8));
                }
            }
            if (c.getResponseCode() != 200) throw new Exception("HTTP " + c.getResponseCode() + " " + url);
            try (InputStream in = c.getInputStream()) {
                ByteArrayOutputStream out = new ByteArrayOutputStream();
                byte[] buf = new byte[16384];
                int n;
                while ((n = in.read(buf)) > 0) {
                    out.write(buf, 0, n);
                    if (out.size() > max) throw new Exception("massa gran: " + url);
                }
                return out.toByteArray();
            }
        } finally {
            c.disconnect();
        }
    }
}
