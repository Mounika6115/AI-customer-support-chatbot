from flask import Blueprint,request
from flask_jwt_extended import create_access_token
from models import db,User
auth_bp=Blueprint("auth",__name__)
@auth_bp.post("/register")
def register():
    d=request.get_json() or {}
    if not all(d.get(k) for k in ("name","email","password")): return {"error":"Missing required fields"},400
    if User.query.filter_by(email=d["email"].lower()).first(): return {"error":"Email already registered"},409
    u=User(name=d["name"],email=d["email"].lower(),role="customer"); u.set_password(d["password"]); db.session.add(u); db.session.commit()
    return {"message":"registered"},201
@auth_bp.post("/login")
def login():
    d=request.get_json() or {}; u=User.query.filter_by(email=d.get("email","").lower()).first()
    if not u or not u.check_password(d.get("password","")): return {"error":"Invalid credentials"},401
    return {"token":create_access_token(identity=str(u.id),additional_claims={"role":u.role,"name":u.name}),"user":{"id":u.id,"name":u.name,"role":u.role}}
