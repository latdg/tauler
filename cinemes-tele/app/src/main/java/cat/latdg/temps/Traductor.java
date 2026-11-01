package cat.latdg.temps;

import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;

/**
 * Del castellà al català amb el traductor de Softcatalà (Apertium, api.softcatala.org), per als textos de la
 * cartellera que només arriben en castellà: la sinopsi de TMDB quan no la té en català, i el gènere i l'edat de
 * l'Odeon. Cada text es tradueix una sola vegada: les traduccions es desen a traduccions.json.
 */
final class Traductor {

    static final String API = "https://api.softcatala.org/traductor/v1/translate";

    private final File fitxer;
    private final JSONObject desades;
    private boolean canvis;

    Traductor(File dir) {
        fitxer = new File(dir, "traduccions.json");
        JSONObject d;
        try {
            d = new JSONObject(new String(Files.readAllBytes(fitxer.toPath()), StandardCharsets.UTF_8));
        } catch (Exception e) {
            d = new JSONObject();
        }
        desades = d;
    }

    /** El text en català; si el traductor no respon, el text original (es tornarà a provar la vegada següent). */
    String tradueix(String castella) {
        if (castella == null || castella.trim().isEmpty()) return castella;
        String ja = desades.optString(castella, null);
        if (ja != null) return ja;
        try {
            HttpURLConnection c = (HttpURLConnection) new URL(API).openConnection();
            c.setConnectTimeout(10000);
            c.setReadTimeout(20000);
            c.setRequestMethod("POST");
            c.setDoOutput(true);
            c.setRequestProperty("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8");
            String cos = "langpair=" + URLEncoder.encode("es|ca", "UTF-8") + "&markUnknown=no&q="
                    + URLEncoder.encode(castella, "UTF-8");
            try (OutputStream o = c.getOutputStream()) {
                o.write(cos.getBytes(StandardCharsets.UTF_8));
            }
            try {
                if (c.getResponseCode() != 200) return castella;
                java.io.ByteArrayOutputStream buf = new java.io.ByteArrayOutputStream();
                try (java.io.InputStream in = c.getInputStream()) {
                    byte[] b = new byte[8192];
                    int n;
                    while ((n = in.read(b)) > 0 && buf.size() < 256 * 1024) buf.write(b, 0, n);
                }
                String resposta = buf.toString("UTF-8");
                String catala = new JSONObject(resposta).getJSONObject("responseData").optString("translatedText");
                if (catala.isEmpty()) return castella;
                desades.put(castella, catala);
                canvis = true;
                return catala;
            } finally {
                c.disconnect();
            }
        } catch (Exception e) {
            return castella;
        }
    }

    void desa() {
        if (!canvis) return;
        try (OutputStream o = new FileOutputStream(fitxer)) {
            o.write(desades.toString().getBytes(StandardCharsets.UTF_8));
        } catch (Exception ignored) {
            // es tornarà a traduir la propera vegada
        }
    }
}
