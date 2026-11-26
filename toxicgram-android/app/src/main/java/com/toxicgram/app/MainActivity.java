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
import org.json.JSONArray;
import android.os.Handler;
import android.os.Looper;
import android.content.ClipboardManager;
import android.content.ClipData;
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
    private int page=0;
    private final Handler timer=new Handler(Looper.getMainLooper());
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
        page++;timer.removeCallbacksAndMessages(null);
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
    interface Result { void accept(JSONObject data) throws Exception; }
    void call(String method,String path,JSONObject body,Result done,TextView error,Button busy){
        final int current=page;final String token=session;
        if(busy!=null)busy.setEnabled(false);
        network.execute(()->{
            try {
                JSONObject data=request(method,path,body,token);
                runOnUiThread(()->{
                    if(isDestroyed()||current!=page)return;
                    if(busy!=null)busy.setEnabled(true);
                    try{done.accept(data);}catch(Exception e){if(error!=null)error.setText("Не удалось обработать ответ.");}
                });
            } catch(Exception e){
                runOnUiThread(()->{
                    if(isDestroyed()||current!=page)return;
                    if(busy!=null)busy.setEnabled(true);
                    if(e instanceof ApiError&&((ApiError)e).status==401){session=null;account=null;showLogin();status.setText("Сеанс завершён. Войдите снова.");return;}
                    if(error!=null)error.setText(e instanceof ApiError&&((ApiError)e).status==404?"Аккаунт не найден.":e instanceof ApiError&&((ApiError)e).status==429?"Слишком много запросов.":"Ошибка соединения. Повторите позже.");
                });
            }
        });
    }
    JSONObject data(String key,String value){
        JSONObject o=new JSONObject();try{o.put(key,value);}catch(Exception ignored){}return o;
    }
    void showAccount(){
        screen();
        text("Toxicgram",30,INK,true,12);
        TextView identity=text(account,15,MUTED,false,12);
        identity.setOnClickListener(v->{
            ClipboardManager clipboard=(ClipboardManager)getSystemService(CLIPBOARD_SERVICE);
            clipboard.setPrimaryClip(ClipData.newPlainText("Toxicgram ID",account));
            Toast.makeText(this,"Номер скопирован",Toast.LENGTH_SHORT).show();
        });
        Button profile=button("Мой профиль");profile.setOnClickListener(v->showProfile());
        text("Чаты",23,INK,true,8);
        EditText peer=field("Номер друга TG-1234-5678",InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_FLAG_CAP_CHARACTERS,16);
        Button open=button("Начать чат");
        TextView info=text("",14,MUTED,false,8);
        open.setOnClickListener(v->{
            String id=peer.getText().toString().trim().toUpperCase(Locale.ROOT);
            if(!id.matches("TG-[0-9]{4}-[0-9]{4}")){info.setText("Введите номер Toxicgram.");return;}
            call("GET","/v1/users/"+id,null,d->showChat(id,d.getString("name")),info,open);
        });
        LinearLayout list=new LinearLayout(this);list.setOrientation(LinearLayout.VERTICAL);root.addView(list,new LinearLayout.LayoutParams(-1,-2));
        Button refresh=button("Обновить чаты");
        Runnable load=()->call("GET","/v1/chats",null,d->{
            list.removeAllViews();JSONArray arr=d.getJSONArray("chats");
            if(arr.length()==0){TextView empty=new TextView(this);empty.setTextColor(MUTED);empty.setText("Пока нет сообщений");empty.setPadding(dp(8),dp(16),dp(8),dp(16));list.addView(empty);}
            for(int i=0;i<arr.length();i++){
                JSONObject row=arr.getJSONObject(i);String id=row.getString("number"),name=row.getString("name");
                TextView item=new TextView(this);item.setText(name+"\n"+row.optString("text"));item.setTextColor(INK);item.setTextSize(16);item.setMaxLines(2);item.setPadding(dp(16),dp(14),dp(16),dp(14));item.setBackground(shape(CARD,12));
                LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,-2);p.bottomMargin=dp(8);list.addView(item,p);item.setOnClickListener(v->showChat(id,name));
            }
            info.setText("");
        },info,refresh);
        refresh.setOnClickListener(v->load.run());load.run();
        Button out=button("Выйти");
        out.setOnClickListener(v->call("POST","/v1/auth/logout",null,d->{session=null;account=null;showLogin();},info,out));
    }
    void showProfile(){
        screen();text("Мой профиль",28,INK,true,16);text(account,16,MUTED,false,24);
        EditText name=field("Имя",InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_FLAG_CAP_SENTENCES,64);
        Button save=button("Сохранить");TextView info=text("",14,MUTED,false,12);
        call("GET","/v1/profile",null,d->name.setText(d.getString("name")),info,save);
        save.setOnClickListener(v->{String value=name.getText().toString().trim();if(value.isEmpty()){info.setText("Введите имя.");return;}call("PUT","/v1/profile",data("name",value),d->showAccount(),info,save);});
        button("Назад").setOnClickListener(v->showAccount());
    }
    void showChat(String peer,String name){
        screen();final int current=page;
        text(name,24,INK,true,4);text(peer,13,MUTED,false,12);
        button("‹ Чаты").setOnClickListener(v->showAccount());
        LinearLayout history=new LinearLayout(this);history.setOrientation(LinearLayout.VERTICAL);
        ScrollView messages=new ScrollView(this);messages.addView(history);root.addView(messages,new LinearLayout.LayoutParams(-1,dp(300)));
        EditText composer=field("Сообщение",InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_FLAG_CAP_SENTENCES,4000);
        Button send=button("Отправить");TextView info=text("",14,MUTED,false,8);
        final long[] last={-1};
        Runnable load=()->call("GET","/v1/chats/"+peer+"/messages",null,d->{
            JSONArray arr=d.getJSONArray("messages");long newest=arr.length()==0?0:arr.getJSONObject(arr.length()-1).getLong("id");
            if(newest==last[0])return;last[0]=newest;history.removeAllViews();
            for(int i=0;i<arr.length();i++){
                JSONObject msg=arr.getJSONObject(i);boolean mine=account.equals(msg.getString("sender"));
                TextView bubble=new TextView(this);bubble.setText(msg.getString("text"));bubble.setTextColor(INK);bubble.setTextSize(16);bubble.setPadding(dp(14),dp(10),dp(14),dp(10));bubble.setMaxWidth(dp(280));bubble.setBackground(shape(mine?0xff5539a5:CARD,16));
                LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-2,-2);p.gravity=mine?Gravity.RIGHT:Gravity.LEFT;p.bottomMargin=dp(8);history.addView(bubble,p);
            }
            messages.post(()->messages.fullScroll(View.FOCUS_DOWN));
        },info,null);
        send.setOnClickListener(v->{
            String value=composer.getText().toString().trim();if(value.isEmpty())return;
            JSONObject body=data("recipient",peer);try{body.put("text",value);}catch(Exception ignored){}
            call("POST","/v1/messages",body,d->{if(composer.getText().toString().trim().equals(value))composer.setText("");info.setText("");load.run();},info,send);
        });
        load.run();
        timer.postDelayed(new Runnable(){public void run(){if(isDestroyed()||page!=current)return;if(hasWindowFocus())load.run();timer.postDelayed(this,5000);}},5000);
    }
    @Override public void onBackPressed(){if(session!=null){showAccount();}else super.onBackPressed();}
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
                byte[] b=new byte[4096];int count;while((count=in.read(b))!=-1){if(out.size()+count>2097152)throw new IOException("Too large");out.write(b,0,count);}
                return new JSONObject(out.toString("UTF-8"));
            }
        }finally{conn.disconnect();}
    }
    @Override protected void onDestroy(){timer.removeCallbacksAndMessages(null);network.shutdownNow();super.onDestroy();}
}
