package main
import("crypto/ecdh";"crypto/rand";"encoding/base64";"encoding/json";"io";"net/http";"strings";"testing";webpush "github.com/SherClockHolmes/webpush-go")
type fakeClient struct{t *testing.T;called bool}
func(c *fakeClient)Do(r *http.Request)(*http.Response,error){c.called=true;b,_:=io.ReadAll(r.Body);if r.Method!="POST"||r.Header.Get("Content-Encoding")!="aes128gcm"||len(b)==0||strings.Contains(string(b),"visible message"){c.t.Fatal("push was not encrypted")};if !strings.HasPrefix(r.Header.Get("Authorization"),"vapid "){c.t.Fatal("missing VAPID signature")};return &http.Response{StatusCode:201,Body:io.NopCloser(strings.NewReader(""))},nil}
func TestPushEncryptionAndEndpointPolicy(t *testing.T){
 for _,s:=range []string{"http://web.push.apple.com/a","https://web.push.apple.com.invalid/a","https://127.0.0.1/a","https://web.push.apple.com:8443/a","https://user:pass@web.push.apple.com/a"}{if allowedEndpoint(s){t.Fatal("unsafe endpoint accepted")}}
 private,public,e:=webpush.GenerateVAPIDKeys();if e!=nil{t.Fatal(e)};key,e:=ecdh.P256().GenerateKey(rand.Reader);if e!=nil{t.Fatal(e)};auth:=make([]byte,16);rand.Read(auth)
 in:=Input{PrivateKey:private,PublicKey:public,Subscription:webpush.Subscription{Endpoint:"https://web.push.apple.com/test",Keys:webpush.Keys{P256dh:base64.RawURLEncoding.EncodeToString(key.PublicKey().Bytes()),Auth:base64.RawURLEncoding.EncodeToString(auth)}},Payload:json.RawMessage(`{"body":"visible message"}`)}
 client:=&fakeClient{t:t};status,e:=send(in,client);if e!=nil||status!=201||!client.called{t.Fatal("encrypted push failed",e,status)}
 client.called=false;in.Subscription.Endpoint="https://localhost/private";if _,e=send(in,client);e==nil||client.called{t.Fatal("unsafe endpoint reached transport")}
}
