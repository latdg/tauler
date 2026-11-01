package cat.latdg.temps;

import java.io.IOException;
import java.net.InetAddress;
import java.net.Socket;

import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLSocket;
import javax.net.ssl.SSLSocketFactory;

/** Connexions TLS limitades a TLS 1.2, per als servidors que tallen la salutació TLS 1.3 d'Android 10. */
final class Tls12 extends SSLSocketFactory {

    private static SSLSocketFactory unica;
    private final SSLSocketFactory base;

    private Tls12(SSLSocketFactory base) {
        this.base = base;
    }

    static synchronized SSLSocketFactory factoria() throws Exception {
        if (unica == null) {
            SSLContext ctx = SSLContext.getInstance("TLSv1.2");
            ctx.init(null, null, null);
            unica = new Tls12(ctx.getSocketFactory());
        }
        return unica;
    }

    private static Socket tls12(Socket s) {
        if (s instanceof SSLSocket) ((SSLSocket) s).setEnabledProtocols(new String[]{"TLSv1.2"});
        return s;
    }

    @Override public String[] getDefaultCipherSuites() { return base.getDefaultCipherSuites(); }
    @Override public String[] getSupportedCipherSuites() { return base.getSupportedCipherSuites(); }
    @Override public Socket createSocket(Socket s, String host, int port, boolean autoClose) throws IOException {
        return tls12(base.createSocket(s, host, port, autoClose));
    }
    @Override public Socket createSocket(String host, int port) throws IOException {
        return tls12(base.createSocket(host, port));
    }
    @Override public Socket createSocket(String host, int port, InetAddress local, int localPort) throws IOException {
        return tls12(base.createSocket(host, port, local, localPort));
    }
    @Override public Socket createSocket(InetAddress host, int port) throws IOException {
        return tls12(base.createSocket(host, port));
    }
    @Override public Socket createSocket(InetAddress host, int port, InetAddress local, int localPort) throws IOException {
        return tls12(base.createSocket(host, port, local, localPort));
    }
}
