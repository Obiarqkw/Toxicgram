/*
 * Toxicgram REST adapter for the original Telegram Android client.
 * GPL-2.0-or-later, consistent with the enclosing project.
 * Unsupported RPCs fail explicitly; never fall back to Telegram.
 */
package org.telegram.tgnet;

import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import org.json.JSONArray;
import org.json.JSONObject;
import org.telegram.messenger.ApplicationLoader;
import org.telegram.messenger.Utilities;
import java.io.*;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import javax.net.ssl.HttpsURLConnection;

public final class ToxicgramRpc {
    public static final boolean ENABLED=true;
    private static final String BASE="https://toxicgram-auth-production.up.railway.app";
    private static final ExecutorService IO=Executors.newSingleThreadExecutor();
    private static final String KEY="toxicgram_original_session";
    private ToxicgramRpc(){}
    private static SharedPreferences prefs(int a){
        return ApplicationLoader.applicationContext.getSharedPreferences("toxicgram_rest_"+a,0);
    }
    private static SecretKey key()throws Exception{
        KeyStore ks=KeyStore.getInstance("AndroidKeyStore");ks.load(null);
        if(ks.containsAlias(KEY))return (SecretKey)ks.getKey(KEY,null);
        KeyGenerator gen=KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore");
        gen.init(new KeyGenParameterSpec.Builder(KEY,KeyProperties.PURPOSE_ENCRYPT|KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());
        return gen.generateKey();
    }
    private static void store(int a,String token,String number)throws Exception{
        Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.ENCRYPT_MODE,key());
        byte[] encrypted=cipher.doFinal(token.getBytes(StandardCharsets.UTF_8));
        if(!prefs(a).edit().putString("token",Base64.encodeToString(encrypted,Base64.NO_WRAP))
            .putString("iv",Base64.encodeToString(cipher.getIV(),Base64.NO_WRAP)).putString("number",number).commit())
            throw new IOException("Cannot persist session");
    }
    private static String token(int a)throws Exception{
        String data=prefs(a).getString("token",""),iv=prefs(a).getString("iv","");
        if(data.isEmpty()||iv.isEmpty())throw new ApiError(401,"AUTH_KEY_UNREGISTERED");
        Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE,key(),new GCMParameterSpec(128,Base64.decode(iv,Base64.NO_WRAP)));
        return new String(cipher.doFinal(Base64.decode(data,Base64.NO_WRAP)),StandardCharsets.UTF_8);
    }
    private static class ApiError extends IOException {
        final int code;final String type;
        ApiError(int c,String t){code=c;type=t;}
    }
    private static JSONObject http(String method,String path,JSONObject body,String token)throws Exception{
        HttpsURLConnection conn=(HttpsURLConnection)new URL(BASE+path).openConnection();
        try{
            conn.setConnectTimeout(15000);conn.setReadTimeout(20000);conn.setRequestMethod(method);
            conn.setInstanceFollowRedirects(false);conn.setRequestProperty("Accept","application/json");
            if(token!=null)conn.setRequestProperty("Authorization","Bearer "+token);
            if(body!=null){conn.setDoOutput(true);conn.setRequestProperty("Content-Type","application/json");
                try(OutputStream o=conn.getOutputStream()){o.write(body.toString().getBytes(StandardCharsets.UTF_8));}}
            int status=conn.getResponseCode();
            if(status<200||status>=300)throw new ApiError(status,status==401?"AUTH_KEY_UNREGISTERED":status==429?"FLOOD_WAIT_60":status==404?"PEER_ID_INVALID":"TOXICGRAM_SERVER_ERROR");
            try(InputStream in=conn.getInputStream();ByteArrayOutputStream out=new ByteArrayOutputStream()){
                byte[] buffer=new byte[8192];int n;while((n=in.read(buffer))!=-1){if(out.size()+n>2*1024*1024)throw new IOException("Response too large");out.write(buffer,0,n);}
                return new JSONObject(out.toString("UTF-8"));
            }
        }finally{conn.disconnect();}
    }
    private static String phone(String raw){
        String v=raw.replaceAll("[^0-9]","");
        return "+"+v;
    }
    public static long userId(String number){
        if(!number.matches("TG-[0-9]{4}-[0-9]{4}"))throw new IllegalArgumentException("Invalid internal identifier");
        return 100000000L+Long.parseLong(number.replaceAll("[^0-9]",""));
    }
    private static TLRPC.TL_user user(JSONObject p,boolean self)throws Exception{
        TLRPC.TL_user u=new TLRPC.TL_user();
        u.id=userId(p.getString("number"));u.first_name=p.optString("name",p.optString("phone","Toxicgram"));
        u.phone=p.optString("phone","").replace("+","");u.username=p.optString("username","");
        u.self=self;u.flags=2|16|(u.username.isEmpty()?0:8)|(self?1024:0);
        u.access_hash=u.id;u.flags|=1;
        return u;
    }
    public static void send(int account,TLObject request,RequestDelegate completion,RequestDelegateTimestamp timestamp){
        IO.execute(()->{
            TLObject response=null;TLRPC.TL_error error=null;
            try{response=dispatch(account,request);}
            catch(ApiError e){error=new TLRPC.TL_error();error.code=e.code;error.text=e.type;}
            catch(Exception e){error=new TLRPC.TL_error();error.code=500;error.text="TOXICGRAM_REQUEST_FAILED";}
            final TLObject result=response;final TLRPC.TL_error failure=error;
            Utilities.stageQueue.postRunnable(()->{
                if(completion!=null)completion.run(result,failure);
                else if(timestamp!=null)timestamp.run(result,failure,System.currentTimeMillis());
            });
        });
    }
    private static TLObject dispatch(int a,TLObject req)throws Exception{
        if(req instanceof TLRPC.TL_auth_sendCode || req instanceof TLRPC.TL_auth_resendCode){
            String raw=req instanceof TLRPC.TL_auth_sendCode?((TLRPC.TL_auth_sendCode)req).phone_number:((TLRPC.TL_auth_resendCode)req).phone_number;
            if(!phone(raw).matches("\\+(7|1|388)000[0-9]{7}"))throw new ApiError(400,"PHONE_NUMBER_INVALID");
            // The bot issues the code. This response only opens the original code-entry screen.
            TLRPC.TL_auth_sentCode result=new TLRPC.TL_auth_sentCode();
            TLRPC.TL_auth_sentCodeTypeApp type=new TLRPC.TL_auth_sentCodeTypeApp();
            type.length=6;result.type=type;result.phone_code_hash="toxicgram-bot";result.timeout=300;
            return result;
        }
        if(req instanceof TLRPC.TL_auth_signIn){
            TLRPC.TL_auth_signIn sign=(TLRPC.TL_auth_signIn)req;
            if(sign.phone_code==null||!sign.phone_code.matches("[0-9]{6}"))throw new ApiError(400,"PHONE_CODE_INVALID");
            JSONObject login;
            try{login=http("POST","/v1/auth/verify",new JSONObject().put("number",phone(sign.phone_number)).put("code",sign.phone_code),null);}
            catch(ApiError e){if(e.code==401)throw new ApiError(400,"PHONE_CODE_INVALID");throw e;}
            String t=login.getString("access_token");
            JSONObject profile=http("GET","/v1/me",null,t);
            TLRPC.TL_auth_authorization auth=new TLRPC.TL_auth_authorization();
            auth.user=user(profile,true);
            store(a,t,profile.getString("number"));return auth;
        }
        if(req instanceof TLRPC.TL_auth_logOut){
            http("POST","/v1/auth/logout",null,token(a));prefs(a).edit().clear().commit();
            return new TLRPC.TL_auth_loggedOut();
        }
        // All unported methods fail closed. No native MTProto or official Telegram RPC fallback.
        throw new ApiError(501,"TOXICGRAM_METHOD_NOT_IMPLEMENTED");
    }
}
