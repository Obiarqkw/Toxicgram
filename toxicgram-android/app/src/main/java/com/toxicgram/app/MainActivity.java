package com.toxicgram.app;

import android.app.Activity;
import android.os.Bundle;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.view.Gravity;
import android.view.View;
import android.widget.*;
import android.text.InputType;
import android.text.InputFilter;
import org.json.JSONObject;
import java.net.URL;
import javax.net.ssl.HttpsURLConnection;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.Executors;
import java.util.concurrent.ExecutorService;
import java.util.Locale;

public class MainActivity extends Activity {
    private static final String BASE = "https://toxicgram-auth-production.up.railway.app";
    private static final int BG=0xff10111a, CARD=0xff1d1e2b, INK=0xfff3f1ff, MUTED=0xffa9a7bb, PURPLE=0xff8158e8;
    private final ExecutorService network=Executors.newSingleThreadExecutor();
    private String session, account;
    private LinearLayout root;
    private TextView status;
    private EditText number, code;
    private Button submit;
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().setStatusBarColor(BG);
        getWindow().setNavigationBarColor(BG);
        showLogin();
    }
    int dp(float v){return (int)(getResources().getDisplayMetrics().density*v+0.5f);}
    GradientDrawable shape(int color,int radius){
        GradientDrawable d=new GradientDrawable();d.setColor(color);d.setCornerRadius(dp(radius));return d;
    }
    void screen(){
        ScrollView sc=new ScrollView(this);sc.setFillViewport(true);sc.setBackgroundColor(BG);
        root=new LinearLayout(this);root.setOrientation(LinearLayout.VERTICAL);root.setPadding(dp(24),dp(48),dp(24),dp(28));
        root.setGravity(Gravity.CENTER_HORIZONTAL);
        sc.addView(root,new ScrollView.LayoutParams(-1,-2));setContentView(sc);
    }
    TextView text(String s,int size,int color,boolean bold,int margin){
        TextView t=new TextView(this);t.setText(s);t.setTextSize(size);t.setTextColor(color);t.setGravity(Gravity.CENTER);
        if(bold)t.setTypeface(Typeface.DEFAULT,Typeface.BOLD);
        LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,-2);p.bottomMargin=dp(margin);root.addView(t,p);return t;
    }
    EditText field(String hint,int type,int length){
        EditText e=new EditText(this);e.setTextColor(INK);e.setHintTextColor(MUTED);e.setHint(hint);e.setTextSize(17);
        e.setSingleLine();e.setInputType(type);e.setFilters(new InputFilter[]{new InputFilter.LengthFilter(length)});
        e.setPadding(dp(16),0,dp(16),0);e.setBackground(shape(CARD,16));
        LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,dp(60));p.bottomMargin=dp(12);root.addView(e,p);return e;
    }
    Button button(String label){
        Button b=new Button(this);b.setText(label);b.setAllCaps(false);b.setTextColor(Color.WHITE);b.setTextSize(16);
        b.setBackground(shape(PURPLE,16));
        LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,dp(54));p.topMargin=dp(12);p.bottomMargin=dp(12);root.addView(b,p);return b;
    }
    void showLogin(){
        screen();
        TextView logo=text("T",38,Color.WHITE,true,24);logo.setBackground(shape(PURPLE,24));
        LinearLayout.LayoutParams lp=new LinearLayout.LayoutParams(dp(84),dp(84));lp.bottomMargin=dp(24);logo.setLayoutParams(lp);
        text("Toxicgram",32,INK,true,12);
        text("Вход в свой аккаунт",20,INK,true,8);
        text("Откройте бота Toxicgram в Telegram, отправьте /code и введите выданный виртуальный номер и код.",15,MUTED,false,28);
        number=field("TG-1234-5678",InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_FLAG_CAP_CHARACTERS,16);
        code=field("Код из 6 цифр",InputType.TYPE_CLASS_NUMBER|InputType.TYPE_NUMBER_VARIATION_PASSWORD,6);
        submit=button("Войти");
        status=text("",14,MUTED,false,16);
        text("Используйте только код Toxicgram, не код входа в Telegram.",13,MUTED,false,16);
        submit.setOnClickListener(v->login());
    }
    void login(){
        String n=number.getText().toString().trim().toUpperCase(Locale.ROOT), c=code.getText().toString().trim();
        if(!n.matches("TG-[0-9]{4}-[0-9]{4}")||!c.matches("[0-9]{6}")){status.setText("Проверьте формат номера и кода.");return;}
        submit.setEnabled(false);status.setText("Подключение...");
        network.execute(()->{
            try{
                JSONObject body=new JSONObject().put("number",n).put("code",c);
                JSONObject response=request("POST","/v1/auth/verify",body,null);
                String token=response.getString("access_token"), id=response.getString("number");
                JSONObject profile=request("GET","/v1/me",null,token);
                if(!id.equals(profile.getString("number")))throw new IOException("Account mismatch");
                runOnUiThread(()->{if(isFinishing()||isDestroyed())return;session=token;account=id;showAccount();});
            }catch(Exception e){
                runOnUiThread(()->{if(isFinishing()||isDestroyed())return;submit.setEnabled(true);status.setText(e instanceof ApiError?(((ApiError)e).status==429?"Слишком много попыток. Повторите позже.":((ApiError)e).status==401?"Неверный или просроченный код. Получите новый.":"Сервер временно недоступен."):"Не удалось подключиться к серверу.");});
            }
        });
    }
    void showAccount(){
        screen();text("Toxicgram",30,INK,true,28);text("Вы вошли в аккаунт",20,INK,true,12);
        text(account,24,PURPLE,true,24);
        text("Тестовая сборка регистрации. Чаты пока не подключены.",15,MUTED,false,18);
        Button out=button("Выйти");status=text("",14,MUTED,false,12);
        out.setOnClickListener(v->{out.setEnabled(false);String token=session;network.execute(()->{
            try{request("POST","/v1/auth/logout",null,token);runOnUiThread(()->{session=null;account=null;if(!isDestroyed())showLogin();});}
            catch(Exception e){runOnUiThread(()->{if(!isDestroyed()){out.setEnabled(true);status.setText("Не удалось завершить сеанс. Повторите попытку.");}});}
        });});
    }
    static class ApiError extends IOException{int status;ApiError(int s){status=s;}}
    JSONObject request(String method,String path,JSONObject body,String token)throws Exception{
        HttpsURLConnection conn=(HttpsURLConnection)new URL(BASE+path).openConnection();
        try{
            conn.setConnectTimeout(15000);conn.setReadTimeout(15000);conn.setRequestMethod(method);
            conn.setInstanceFollowRedirects(false);conn.setRequestProperty("Accept","application/json");
            if(token!=null)conn.setRequestProperty("Authorization","Bearer "+token);
            if(body!=null){conn.setDoOutput(true);conn.setRequestProperty("Content-Type","application/json");try(OutputStream out=conn.getOutputStream()){out.write(body.toString().getBytes(StandardCharsets.UTF_8));}}
            int response=conn.getResponseCode();if(response<200||response>=300)throw new ApiError(response);
            try(InputStream in=conn.getInputStream();ByteArrayOutputStream out=new ByteArrayOutputStream()){
                byte[] b=new byte[4096];int count;while((count=in.read(b))!=-1){if(out.size()+count>65536)throw new IOException("Too large");out.write(b,0,count);}
                return new JSONObject(out.toString("UTF-8"));
            }
        }finally{conn.disconnect();}
    }
    @Override protected void onDestroy(){network.shutdownNow();super.onDestroy();}
}
