// Private helper: VAPID credentials and subscriptions arrive only over stdin.
package main

import (
 "encoding/base64"
 "encoding/json"
 "errors"
 "fmt"
 "io"
 "net/http"
 "net/url"
 "os"
 "strings"
 "time"
 webpush "github.com/SherClockHolmes/webpush-go"
)
type Input struct {
 Mode string `json:"mode"`
 PrivateKey string `json:"private_key"`
 PublicKey string `json:"public_key"`
 Subscription webpush.Subscription `json:"subscription"`
 Payload json.RawMessage `json:"payload"`
}
func allowedEndpoint(raw string) bool {
 u,err:=url.Parse(raw);if err!=nil||u.Scheme!="https"||u.User!=nil||u.Fragment!=""||len(raw)>8192{return false}
 if u.Port()!=""&&u.Port()!="443"{return false}
 h:=strings.ToLower(u.Hostname())
 return strings.HasSuffix(h,".push.apple.com")||h=="fcm.googleapis.com"||h=="updates.push.services.mozilla.com"
}
func decodeLength(value string,n int) bool {b,e:=base64.RawURLEncoding.DecodeString(strings.TrimRight(value,"="));return e==nil&&len(b)==n}
func send(in Input,client webpush.HTTPClient)(int,error){
 if !allowedEndpoint(in.Subscription.Endpoint){return 0,errors.New("endpoint rejected")}
 if !decodeLength(in.PrivateKey,32)||!decodeLength(in.PublicKey,65)||!decodeLength(in.Subscription.Keys.P256dh,65)||!decodeLength(in.Subscription.Keys.Auth,16){return 0,errors.New("key format rejected")}
 if len(in.Payload)==0||len(in.Payload)>2048||!json.Valid(in.Payload){return 0,errors.New("payload rejected")}
 r,e:=webpush.SendNotification(in.Payload,&in.Subscription,&webpush.Options{HTTPClient:client,Subscriber:"https://gateway.example.ts.net/",VAPIDPublicKey:in.PublicKey,VAPIDPrivateKey:in.PrivateKey,TTL:86400,Urgency:webpush.UrgencyHigh});if e!=nil{return 0,e};defer r.Body.Close();io.Copy(io.Discard,io.LimitReader(r.Body,4096));return r.StatusCode,nil
}
func main(){
 var in Input
 if json.NewDecoder(io.LimitReader(os.Stdin,16385)).Decode(&in)!=nil{fmt.Println(`{"error":"invalid input"}`);os.Exit(1)}
 if in.Mode=="generate" {private,public,e:=webpush.GenerateVAPIDKeys();if e!=nil{fmt.Println(`{"error":"key generation failed"}`);os.Exit(1)};json.NewEncoder(os.Stdout).Encode(map[string]string{"private_key":private,"public_key":public});return}
 client:=&http.Client{Timeout:15*time.Second,CheckRedirect:func(*http.Request,[]*http.Request)error{return http.ErrUseLastResponse}}
 status,e:=send(in,client);if e!=nil{json.NewEncoder(os.Stdout).Encode(map[string]interface{}{"sent":false,"error":"push request failed","status":status});os.Exit(1)}
 json.NewEncoder(os.Stdout).Encode(map[string]interface{}{"sent":status>=200&&status<300,"status":status})
}
